# Japan Financial World

This package is the working area for the Japan Financial World Engine.

Design baseline:

- `docs/ontology.md`: objects that can exist in the world.
- `docs/scope.md`: v0 reproduction depth, in-scope behavior, and explicit
  non-goals.
- `docs/architecture.md`: spaces, layers, interaction rules, and scheduler
  order.
- `world/`: the actual world structure: spaces, agents, assets, contracts,
  markets, signals, prices, and ledger.

Implementation should follow the design docs before adding scenario-specific
logic. Cross-space effects must move through asset ownership, contracts, market
prices, information signals, or constraints.
