# Basic Literature Radar Theme

Copy this into `.codex/zotero-literature-radar/research-theme.md` in a workspace and replace the placeholder terms with your own research interests.

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
    "masthead",
    "publication information",
    "table of contents"
  ],
  "ignore_topic_patterns": [
    "unrelated domain",
    "excluded method"
  ],
  "topics": [
    {
      "id": "core-topic",
      "name": "Core topic",
      "tier": "A",
      "weight": 6,
      "required_any": [
        "main concept",
        "application domain"
      ],
      "keywords": [
        "primary method",
        "target metric",
        "optimization",
        "evaluation"
      ]
    },
    {
      "id": "method-adjacent",
      "name": "Method-adjacent topic",
      "tier": "B",
      "weight": 4,
      "required_any": [
        "broader field"
      ],
      "keywords": [
        "modeling",
        "control",
        "prediction",
        "estimation"
      ]
    },
    {
      "id": "implementation-context",
      "name": "Implementation context",
      "tier": "C",
      "weight": 3,
      "required_any": [
        "implementation",
        "dataset",
        "platform"
      ],
      "keywords": [
        "prototype",
        "hardware",
        "software",
        "deployment"
      ]
    }
  ]
}
```

