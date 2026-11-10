# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Target identity for the Isaac Sim 6.2 copy of omni.isaac.assist.

"""Constants for the Isaac Sim 6.2 extension copy.

The API lane is Isaac Sim 6.0. Tags and the target version are 6.2.
Anything that needs a running Kit is listed in ``UNVERIFIED``.
"""

TARGET_VERSION = "6.2.0"
PYTHON_RUNTIME = "3.12"
RUNTIME_PROFILE = "isaacsim-6.2"
API_LANE = "isaacsim-6.0"
ROS2_OMNIGRAPH_NAMESPACE = "isaacsim.ros2.nodes"

UNVERIFIED = (
    "Live Kit load of exts/isaac_6.2/omni.isaac.assist on Isaac Sim 6.2",
    "Python 3.12 site-packages layout inside ~/isaacsim",
    "Whether isaacsim.ros2.bridge.* shims still resolve on Isaac Sim 6.2",
    "Kit SDK version pin for Isaac Sim 6.2",
    "Sticky Note viewport overlay placement inside the Kit viewport",
)
