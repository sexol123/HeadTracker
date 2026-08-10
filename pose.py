from dataclasses import dataclass


@dataclass
class Pose:
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    confidence: float = 0.0
    timestamp: float = 0.0

    def copy(self) -> "Pose":
        return Pose(
            yaw=self.yaw,
            pitch=self.pitch,
            roll=self.roll,
            x=self.x,
            y=self.y,
            z=self.z,
            confidence=self.confidence,
            timestamp=self.timestamp,
        )
