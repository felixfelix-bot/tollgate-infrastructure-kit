# Nostr Kanban Board — net4sats Human Gate

## Board Details
- **Board ID**: `net4sats-human-gate`
- **Kind**: 30301 (Kanbanstr board)
- **Creator npub**: `npub1ux9p69c6t8v8fmwnxerj4l4n5c2d8hyr897ap9lfy25emnhqyyes7wxnqk`
- **Maintainer (Endo)**: `npub1g5rwqnjtwpuuuplr36v82eu2sxkn8fzkc6tdwz8036dzmrqkhgzqm6qq0t`
- **Event ID**: `613c8d312faedba4ca54c6cc56a879646f01b5d970cb619f4193ea7a3454a5de`

## Board URL (once kanbanstr is hosted)
```
https://<kanbanstr-host>/#/board/4506e04e4b7079ce07e38e9875678a81ad33a456c696d708ef8e9a2d8c16ba04/net4sats-human-gate
```

## Columns
1. Backlog
2. In Progress
3. Human Review
4. Blocked
5. Done

## Card Format (Kind 30302)
```
nak event -k 30302 \
  -d <card-uuid> \
  -t 'title=<short title>' \
  -t 'description=<details>' \
  -t 'a=30301:<board-pubkey>:net4sats-human-gate' \
  -t 's=<status>' \
  -t 'rank=<order>' \
  --sec <nsec> \
  wss://relay.damus.io wss://nos.lol
```

## Relays
- wss://relay.damus.io
- wss://nos.lol
