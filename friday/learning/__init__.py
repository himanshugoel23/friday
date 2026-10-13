"""Self-learning tooling for the LISTENING side of calls (docs/LEARNING_AND_BUILD_PLAN.md).

Friday's spoken words stay scripted. What learns is the understanding of what the business said:
``log`` collects vendor utterances, ``queue`` builds the review queue, ``labels`` holds the
labelled evaluation set, ``evaluate`` guards against regressions, ``fewshot`` exports examples.
Nothing here changes what Friday says. All of it is offline and deterministic.
"""
