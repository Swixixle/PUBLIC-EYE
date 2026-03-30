# Sprint 1A — Grounded coalition map (GROUNDED_COALITION_FIX)

## Intent

Remove speculative “likely / probably / tends to …” alignment notes. Every `alignment_note` must either summarize **evidence from sources listed on the receipt** or use the exact fallback: **Not found in sources searched for this receipt.**

## Code touchpoints

| Area | Change |
|------|--------|
| `coalition_service.py` | `COALITION_SYSTEM` rules + banned language; `_sources_catalog_text()`; user prompt includes catalog |
| `models/coalition_map.py` | `CoalitionChainLink.story_url`; `chain_link_from_dict` passes it through |
| `receipt_store.py` | `delete_coalition_map(receipt_id)` |
| `coalition_api.py` | `DELETE /v1/coalition-map/{receipt_id}` |
| `investigation_page.py` | `_one_outlet_row`: italic gray for not-found; `Read coverage ↗` when `story_url` set |

## Regenerate + test

```bash
curl -X DELETE "https://<host>/v1/coalition-map/<receipt_id>"
curl -sS -X POST "https://<host>/v1/coalition-map" \
  -H "Content-Type: application/json" \
  -d '{"receipt_id":"<receipt_id>"}'
# wait for job
curl -s "https://<host>/v1/coalition-map/<receipt_id>" | python3 -c "
import sys,json
d=json.load(sys.stdin)
notes=[i.get('alignment_note','') for pos in ['position_a','position_b']
       for i in (d.get(pos) or {}).get('chain',[])]
bad=[n for n in notes if any(w in n.lower() for w in ['likely','probably','would','tends','typically','generally'])]
print('BAD NOTES:',bad if bad else 'None — PASS')
"
```

Expected: **`None — PASS`**.
