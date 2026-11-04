"""Research service: bounded, budgeted, replayable evidence collection through a search/extraction provider.

It never chooses trades. It receives public company identifiers and public facts only, returns validated
evidence with times, and runs in its own process so it can never block collection or decisions.
"""
