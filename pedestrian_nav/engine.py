from importlib.resources import files
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import folium
from folium.plugins import LocateControl
from geopy.geocoders import Nominatim
import polyline
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

from .backend import run_backend_server

PUBLIC_OSRM_FALLBACK = "https://router.project-osrm.org"


def _find_free_port(starting_port: int) -> int:
    """Finds an available TCP port starting from starting_port."""
    port = starting_port
    while port < starting_port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return starting_port


def _get_cloudflared_bin() -> Optional[str]:
    """Locates cloudflared binary in system PATH or current working directory."""
    bin_path = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if bin_path:
        return bin_path

    for name in ["cloudflared.exe", "cloudflared"]:
        if os.path.exists(name):
            return os.path.abspath(name)
    return None


@st.cache_data(show_spinner=False)
def _cached_geocode(dest: str, lat: float, lng: float, suffix: str) -> Any:
    geo = Nominatim(user_agent="pedestrian_nav_lib", timeout=10)
    d = 0.05
    return geo.geocode(
        f"{dest}, {suffix}",
        viewbox=[(lat - d, lng - d), (lat + d, lng + d)],
        bounded=True,
    )


@st.cache_data(show_spinner=False)
def _cached_osrm_route(
    osrm_url: str, c_lng: float, c_lat: float, d_lng: float, d_lat: float
) -> dict:
    target_url = f"{osrm_url.rstrip('/')}/route/v1/foot/{c_lng},{c_lat};{d_lng},{d_lat}?overview=full&steps=true"
    try:
        res = requests.get(target_url, timeout=4)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass

    fallback_url = f"{PUBLIC_OSRM_FALLBACK}/route/v1/foot/{c_lng},{c_lat};{d_lng},{d_lat}?overview=full&steps=true"
    try:
        return requests.get(fallback_url, timeout=10).json()
    except Exception as e:
        return {"code": "Error", "message": str(e)}


class PedestrianNav:

    def __init__(
        self,
        model_path: Optional[str] = None,
        osrm_url: str = "http://localhost:5000",
        backend_port: int = 5001,
        streamlit_port: int = 8501,
        default_city_suffix: str = "Ho Chi Minh City, Vietnam",
        off_route_tolerance_m: int = 35,
        language_code: str = "vi-VN",
        translation_map: Optional[Dict[str, str]] = None,
        open_browser: bool = True,
        headless: bool = False,
    ):
        self.osrm_url = osrm_url.rstrip("/")
        self.backend_port = backend_port
        self.streamlit_port = streamlit_port
        self.city_suffix = default_city_suffix
        self.off_route_tolerance = off_route_tolerance_m
        self.lang = language_code
        self.open_browser = open_browser and not headless
        self.headless = headless or not open_browser

        self.translation_map = translation_map or {
            "left": "rẽ trái",
            "right": "rẽ phải",
            "slight left": "chếch sang trái",
            "sharp left": "rẽ ngoặt sang trái",
            "slight right": "chếch sang phải",
            "sharp right": "rẽ ngoặt sang phải",
            "straight": "đi thẳng tiếp",
            "uturn": "quay đầu",
        }

        pkg = files("pedestrian_nav")
        self.model_path = model_path or str(
            pkg.joinpath("models/traffic_light.pt")
        )
        self.nav_template = str(pkg.joinpath("templates/nav_engine.html"))
        self.speech_dir = str(pkg.joinpath("speech_component"))

        self._server_started = False
        self._tunnel_started = False
        self.auto_backend_tunnel_url = os.getenv("AUTO_BACKEND_TUNNEL_URL", "")
        self.auto_streamlit_tunnel_url = os.getenv("AUTO_STREAMLIT_TUNNEL_URL", "")

    def start_backend(self) -> None:
        if not self._server_started:
            threading.Thread(
                target=run_backend_server,
                args=(self.model_path, self.osrm_url, self.backend_port),
                daemon=True,
            ).start()
            self._server_started = True

    def start_tunnel(self, timeout_sec: int = 15) -> Tuple[Optional[str], Optional[str]]:
        if self._tunnel_started or self.auto_streamlit_tunnel_url:
            return (
                self.auto_streamlit_tunnel_url or None,
                self.auto_backend_tunnel_url or None,
            )

        cloudflared_bin = _get_cloudflared_bin()
        if not cloudflared_bin:
            print("\n" + "!" * 72, flush=True)
            print("⚠️  'cloudflared' CLI executable not found on your system!", flush=True)
            print("👉  Download cloudflared.exe and place it in this project folder:", flush=True)
            print("    https://github.com/cloudflare/cloudflared/releases/latest", flush=True)
            print("!" * 72 + "\n", flush=True)
            if st.runtime.exists():
                st.warning("⚠️ `cloudflared` CLI not found. Mobile auto-tunneling skipped.")
            return None, None

        self._tunnel_started = True
        pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        print("⚡ Creating HTTPS Cloudflare Tunnel for Mobile Navigation...", flush=True)

        def _launch_tunnel(port: int, target_attr: str):
            proc = subprocess.Popen(
                [
                    cloudflared_bin,
                    "tunnel",
                    "--protocol",
                    "http2",
                    "--url",
                    f"http://localhost:{port}/",
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            start = time.time()
            if proc.stderr:
                while True:
                    line = proc.stderr.readline()
                    if not line:
                        break
                    m = pattern.search(line)
                    if m:
                        found_url = m.group(0)
                        setattr(self, target_attr, found_url)
                        if target_attr == "auto_streamlit_tunnel_url":
                            print("\n" + "=" * 72, flush=True)
                            print("📱 MOBILE NAVIGATION HTTPS TUNNEL READY!", flush=True)
                            print("👉 Open this URL on your phone's browser to connect:\n", flush=True)
                            print(f"    {found_url}\n", flush=True)
                            print("=" * 72 + "\n", flush=True)
                        break
                    if time.time() - start > timeout_sec:
                        break

        threading.Thread(
            target=_launch_tunnel,
            args=(self.backend_port, "auto_backend_tunnel_url"),
            daemon=True,
        ).start()

        threading.Thread(
            target=_launch_tunnel,
            args=(self.streamlit_port, "auto_streamlit_tunnel_url"),
            daemon=True,
        ).start()

        start = time.time()
        while (
            (not self.auto_backend_tunnel_url or not self.auto_streamlit_tunnel_url)
            and (time.time() - start < timeout_sec)
        ):
            time.sleep(0.3)

        return (
            self.auto_streamlit_tunnel_url or None,
            self.auto_backend_tunnel_url or None,
        )

    def launch(self, target_fn: Optional[Callable[[], None]] = None) -> None:
        """Main entry point. If executed via standard python script, bootstraps Streamlit CLI."""
        if not st.runtime.exists():
            # 1. Start Python Backend & Cloudflare Tunnels immediately in parent process
            self.start_backend()
            self.start_tunnel()

            target_script = sys.argv[0]
            streamlit_bin = shutil.which("streamlit")

            free_port = _find_free_port(self.streamlit_port)
            if free_port != self.streamlit_port:
                print(f"⚠️ Port {self.streamlit_port} is in use. Switching to port {free_port}...")
                self.streamlit_port = free_port

            if streamlit_bin:
                cmd = [
                    streamlit_bin,
                    "run",
                    target_script,
                    f"--server.port={self.streamlit_port}",
                ]
            else:
                cmd = [
                    sys.executable,
                    "-m",
                    "streamlit.web.cli",
                    "run",
                    target_script,
                    f"--server.port={self.streamlit_port}",
                ]

            if self.headless or not self.open_browser:
                cmd.append("--server.headless=true")

            if len(sys.argv) > 1:
                cmd.extend(["--", *sys.argv[1:]])

            # Pass tunnel URLs into child Streamlit process environment
            child_env = os.environ.copy()
            if self.auto_streamlit_tunnel_url:
                child_env["AUTO_STREAMLIT_TUNNEL_URL"] = self.auto_streamlit_tunnel_url
            if self.auto_backend_tunnel_url:
                child_env["AUTO_BACKEND_TUNNEL_URL"] = self.auto_backend_tunnel_url

            ret_code = subprocess.call(cmd, env=child_env)
            if ret_code != 0:
                sys.exit(ret_code)
            return

        if target_fn:
            target_fn()
        else:
            self.start_backend()
            self.start_tunnel()
            self.render()

    def _parse_steps(
        self, steps: list
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        actions, waypoints = [], []
        for i, step in enumerate(steps, 1):
            m_type, mod = (
                step["maneuver"]["type"],
                step["maneuver"].get("modifier", ""),
            )
            dist, (slng, slat) = int(
                step.get("distance", 0)
            ), step["maneuver"]["location"]
            raw_name, ref = step.get("name", "").strip(), step.get(
                "ref", ""
            ).strip()
            has_name = bool(raw_name or ref)
            street = (
                raw_name if raw_name else (ref if ref else "con hẻm hoặc lối đi")
            )

            if m_type == "depart":
                act = (
                    f"Bắt đầu đi thẳng về phía trước trên **{street}**"
                    if has_name
                    else "Bắt đầu di chuyển thẳng theo **lối đi hiện tại**"
                )
                sp = (
                    f"Bắt đầu đi thẳng về phía trước trên {street}"
                    if has_name
                    else "Bắt đầu di chuyển thẳng theo lối đi hiện tại"
                )
            elif m_type == "arrive":
                act, sp = "🎉 Đã đến điểm đến!", "Bạn đã đến điểm đến ngay phía trước!"
            else:
                turn = self.translation_map.get(mod, "đi thẳng tiếp")
                act, sp = (
                    f"**{turn.capitalize()}** vào **{street}**",
                    f"{turn} vào {street}",
                )

            dist_txt = f" ({dist}m)" if dist > 0 else ""
            actions.append(f"**{i}.** {act}{dist_txt}")
            waypoints.append({
                "step": i,
                "speech": sp,
                "street": street,
                "lat": slat,
                "lng": slng,
                "m_type": m_type,
            })

        return actions, waypoints

    def render(
        self,
        backend_api_url: str = "",
        map_height: int = 400,
        map_width: int = 350,
    ) -> None:
        if not st.runtime.exists():
            self.launch()
            return

        self.start_backend()
        self.start_tunnel()

        if self.auto_streamlit_tunnel_url:
            st.success(
                f"📱 **Mở URL sau trên điện thoại để dùng Camera/GPS:** `{self.auto_streamlit_tunnel_url}`"
            )

        location = get_geolocation()
        if not location:
            st.warning("Awaiting GPS location permission...")
            st.stop()

        c_lat, c_lng = (
            location["coords"]["latitude"],
            location["coords"]["longitude"],
        )
        st.success(f"GPS Locked: {c_lat:.5f}, {c_lng:.5f}")

        api_url = (
            backend_api_url
            or self.auto_backend_tunnel_url
            or f"http://localhost:{self.backend_port}"
        )

        speech = components.declare_component(
            "speech_input", path=self.speech_dir
        )
        spoken = speech(key="lib_speech")
        if spoken:
            st.session_state["active_destination"] = spoken

        destination = st.session_state.get("active_destination")

        if destination:
            st.write(f"🎯 **Điểm đến đã nhận dạng:** `{destination}`")
            with st.spinner("Đang tìm đường đi..."):
                loc: Any = _cached_geocode(
                    destination, c_lat, c_lng, self.city_suffix
                )
                if not loc:
                    st.error("Không tìm thấy vị trí trên bản đồ.")
                    return

                d_lat, d_lng = loc.latitude, loc.longitude
                route_res = _cached_osrm_route(
                    self.osrm_url, c_lng, c_lat, d_lng, d_lat
                )
                if route_res.get("code") != "Ok":
                    st.error("Không tìm thấy tuyến đường đi bộ.")
                    return

                leg = route_res["routes"][0]["legs"][0]
                coords = polyline.decode(route_res["routes"][0]["geometry"])

                m = folium.Map(location=[c_lat, c_lng], zoom_start=16)
                LocateControl(
                    auto_start=True,
                    flyTo=True,
                    keepCurrentZoomLevel=True,
                    showDeviceOrientation=False,
                    locateOptions={"enableHighAccuracy": True},
                ).add_to(m)

                folium.PolyLine(coords, color="blue", weight=5).add_to(m)
                folium.Marker([c_lat, c_lng], popup="Start").add_to(m)
                folium.Marker([d_lat, d_lng], popup=destination).add_to(m)
                st_folium(
                    m, width=map_width, height=map_height, returned_objects=[]
                )

                st.info(
                    f"Khoảng cách: {leg['distance']/1000:.2f} km | Thời gian đi bộ: {int(leg['duration']/60)} phút"
                )

                actions, waypoints = self._parse_steps(leg["steps"])
                with st.expander(
                    "📌 Hướng dẫn di chuyển từng bước", expanded=True
                ):
                    for act in actions:
                        st.markdown(act)

                with open(self.nav_template, "r", encoding="utf-8") as f:
                    html = (
                        f.read()
                        .replace(
                            "let waypoints = null; // __WAYPOINTS_JSON__",
                            f"let waypoints = {json.dumps(waypoints, ensure_ascii=False)};",
                        )
                        .replace(
                            "const destLat = 0.0;  // __DEST_LAT__",
                            f"const destLat = {d_lat};",
                        )
                        .replace(
                            "const destLng = 0.0;  // __DEST_LNG__",
                            f"const destLng = {d_lng};",
                        )
                        .replace(
                            "const startLat = 0.0; // __START_LAT__",
                            f"const startLat = {c_lat};",
                        )
                        .replace(
                            "const startLng = 0.0; // __START_LNG__",
                            f"const startLng = {c_lng};",
                        )
                        .replace(
                            'const backendApiUrl = ""; // __BACKEND_API_URL__',
                            f'const backendApiUrl = "{api_url}";',
                        )
                    )

                components.html(html, height=220)