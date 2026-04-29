# World

Canonical project structure:

```text
Project
  World
    Spaces
      Corporate Space
      Investor Space
      Bank / Debt Space
      Exchange Space
      Real Estate Space
      Information Space
      Policy Space
      External / Macro Space

    Agents
    Assets
    Contracts
    Markets
    Signals
    Prices
    Ledger
```

`World` is the container for simulation state. It does not contain ad hoc event
modules. Cross-space effects must move through agents, assets, contracts,
markets, signals, prices, or ledger entries.

## Directory Roles

- `spaces/`: bounded simulation spaces with their own update logic.
- `agents/`: stateful decision-making subjects and their schemas.
- `assets/`: ownable economic objects.
- `contracts/`: obligations and relationships between subjects.
- `markets/`: mechanisms that clear supply and demand.
- `signals/`: observable information, including disclosure, news, ratings, and
  price-derived signals.
- `prices/`: market prices and marks used by other spaces.
- `ledger/`: append-only record of state changes, transactions, and decisions.
