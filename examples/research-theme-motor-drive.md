# Motor Drive Literature Radar Theme

Example theme for motor-drive efficiency, PMSM control, inverter loss, modulation, and traction-drive implementation topics.

```json
{
  "lookback_days": 7,
  "output_dir": "Literature Radar Reports",
  "max_items_per_tier": {
    "A": 8,
    "B": 12,
    "C": 12
  },
  "ignore_title_patterns": [
    "author information",
    "call for papers",
    "contents",
    "corrigendum",
    "editorial",
    "front cover",
    "index",
    "inside back cover",
    "inside front cover",
    "masthead",
    "publication information",
    "table of contents"
  ],
  "ignore_topic_patterns": [
    "battery management",
    "distribution network",
    "grid forming",
    "path planning",
    "photovoltaic",
    "power grid",
    "robot navigation",
    "semiconductor fabrication"
  ],
  "topics": [
    {
      "id": "motor-drive-efficiency-loss",
      "name": "Motor drive efficiency and loss minimization",
      "tier": "A",
      "weight": 6,
      "required_any": [
        "motor drive",
        "permanent magnet synchronous motor",
        "pmsm",
        "electric traction",
        "traction drive"
      ],
      "keywords": [
        "efficiency optimization",
        "energy optimization",
        "loss minimization",
        "copper loss",
        "iron loss",
        "core loss",
        "efficiency map",
        "loss model",
        "minimum loss",
        "minimum current"
      ]
    },
    {
      "id": "trajectory-energy-control",
      "name": "Trajectory optimization and tracking for energy-aware drives",
      "tier": "A",
      "weight": 5,
      "required_any": [
        "motor drive",
        "pmsm",
        "electric traction",
        "traction system"
      ],
      "keywords": [
        "trajectory optimization",
        "trajectory tracking",
        "speed trajectory",
        "energy optimal",
        "energy-efficient control",
        "eco-driving",
        "loss-model-based control"
      ]
    },
    {
      "id": "drive-control-methods",
      "name": "Motor-drive control methods",
      "tier": "B",
      "weight": 4,
      "required_any": [
        "motor drive",
        "pmsm",
        "electric machine",
        "traction"
      ],
      "keywords": [
        "model predictive control",
        "predictive current control",
        "sliding mode control",
        "adaptive control",
        "observer",
        "sensorless control",
        "direct torque control",
        "current control"
      ]
    },
    {
      "id": "inverter-modulation-loss",
      "name": "Inverter loss and modulation implementation",
      "tier": "C",
      "weight": 3,
      "required_any": [
        "inverter",
        "motor drive",
        "traction"
      ],
      "keywords": [
        "inverter loss",
        "switching loss",
        "modulation strategy",
        "space vector modulation",
        "pulsewidth modulation",
        "sic",
        "gan",
        "wide bandgap"
      ]
    }
  ]
}
```

