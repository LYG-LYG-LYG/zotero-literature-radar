# Zotero Literature Radar Research Theme

This file is the workspace-local research theme for `$zotero-literature-radar`.
Edit the JSON block below to customize topics, precision rules, and A/B/C display limits for this workspace.

```json
{
  "lookback_days": 7,
  "output_dir": "Literature Radar Reports",
  "max_items_per_tier": {
    "A": 6,
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
      "id": "core-research-topic",
      "name": "Core research topic",
      "tier": "A",
      "weight": 6,
      "required_any": [
        "your main concept",
        "your key method",
        "your application domain"
      ],
      "keywords": [
        "important keyword",
        "related method",
        "target metric",
        "benchmark",
        "optimization"
      ]
    },
    {
      "id": "adjacent-methods",
      "name": "Adjacent methods and models",
      "tier": "A",
      "weight": 5,
      "required_any": [
        "your main concept",
        "your application domain"
      ],
      "keywords": [
        "modeling",
        "control",
        "prediction",
        "estimation",
        "robustness"
      ]
    },
    {
      "id": "background-methods",
      "name": "Useful background methods",
      "tier": "B",
      "weight": 4,
      "required_any": [
        "your broader field",
        "your application domain"
      ],
      "keywords": [
        "survey",
        "framework",
        "algorithm",
        "experimental validation",
        "case study"
      ]
    },
    {
      "id": "implementation-context",
      "name": "Implementation and context",
      "tier": "C",
      "weight": 3,
      "required_any": [
        "implementation",
        "platform",
        "dataset"
      ],
      "keywords": [
        "prototype",
        "hardware",
        "software",
        "dataset",
        "deployment"
      ]
    }
  ]
}
```

`required_any` is the precision gate: at least one term must appear when the list is non-empty.
`keywords` are scoring/recall terms: matched keywords add score and explain why the paper was selected.
