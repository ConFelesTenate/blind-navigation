import os
import streamlit as st
from pedestrian_nav import PedestrianNav

osrm_url = os.getenv("OSRM_URL", "http://localhost:5000")
nav = PedestrianNav(osrm_url=osrm_url, open_browser=False)


def main():
    st.set_page_config(
        page_title="Pedestrian Navigation Demo",
        page_icon="🚶",
        layout="centered",
    )
    st.title("🚶 Pedestrian Navigation System")
    nav.render()


if __name__ == "__main__":
    nav.launch(main)