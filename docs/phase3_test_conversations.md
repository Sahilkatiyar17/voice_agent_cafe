# Phase 3: scripted test conversations

Run these by hand against `python -m backend.agent.cli`. Each entry lists what to say and
what to check for - not exact wording, since the LLM's phrasing isn't deterministic. Check
the *behavior*: did it call the right tool, read back the right numbers, wait for an
explicit yes before confirming, and stay in scope.

A few scenarios need one-time setup in the database first (noted inline) - use
`docker exec -it cafe_postgres psql -U cafe -d cafe` or the `/docs` Swagger UI's menu
manager endpoint (`POST /menu/refresh` after editing `is_available` directly in the DB).

Mark each ✅ / ❌ as you go. If something fails, note what actually happened - that's raw
material for tuning `prompts.py`, not necessarily a bug in the tools (those are already
tested in `tests/`).

---

## A. Menu search (5)

1. **Not on the menu, with a suggestion.** Say "do you have matar paneer". Expect: it says
   no, and offers Palak Paneer (or similar) as the closest match — mirrors
   `docs/spec.md`'s test hook.
2. **Ambiguous alias.** Say "I'd like a burger". Expect: it doesn't guess — it asks whether
   you mean the chicken or the veggie burger.
3. **Category listing.** Say "what continental items do you have". Expect: a short spoken
   list of the continental section (pizza, pasta, burgers, fries, salad).
4. **Exact hit, price check.** Say "how much is the butter naan". Expect: it calls
   `search_menu`, not the price from memory, and answers Rs 60.
5. **Sold out mid-order.** *Setup:* flip Butter Chicken's `is_available` to false directly
   in the DB (`UPDATE menu_items SET is_available=false WHERE name='Butter Chicken';`), then
   restart the CLI process (menu cache loads at startup). Say "I'll have the butter
   chicken". Expect: it says it's sold out (via `search_menu` or `add_item`'s own check),
   doesn't add it, and asks what else you'd like. *Cleanup:* flip it back afterward.

## B. Ordering (9)

6. **Add a single item.** "I'd like a chicken biryani." Expect: it adds it and states the
   running subtotal.
7. **Add several items in one turn.** "I'd like a chicken biryani and two butter naan."
   Expect: both get added (may take two tool calls), and the summary reflects both.
8. **Add then remove.** Add a burger (pick one after disambiguation), then say "actually
   remove the burger." Expect: `remove_item` or `set_item_quantity(0)` is called, and the
   item disappears from the next readback — mirrors `docs/spec.md`'s test hook.
9. **Change quantity.** After adding one naan, say "make that two." Expect: quantity
   updates to 2, total recalculates.
10. **Ambiguous item mid-order.** Mid-order, say "add a burger too." Expect: same
    disambiguation as scenario 2, not a guess.
11. **Item with a modifier.** "I'll have the butter chicken, extra hot." Expect: it adds the
    item with the "hot" modifier — check the reservation/order summary includes it.
12. **Full happy path.** Order 1-2 items, give a delivery address with pincode `560038`
    (in the seeded delivery area), have it read back the full order and total, say yes.
    Expect: `confirm_order` is called only after your yes, and reports success.
13. **Address outside delivery area.** Same as above but give pincode `999999`. Expect: it
    says plainly that it doesn't deliver there and asks what you'd like to do — no retry,
    no guessing a nearby pincode.
14. **Below minimum order.** Order just one Masala Chai (Rs 90) and try to confirm.
    Expect: `confirm_order` reports the Rs 250 minimum isn't met; it explains this and asks
    if you'd like to add more, rather than confirming anyway.

## C. Reservations (8)

15. **Full booking happy path.** Give a date within 14 days, a time between 11:00-21:30, a
    party size 1-6, your name and phone. Expect: `check_availability` and/or `hold_slot`
    get called, it reads back date/time/party/table, waits for your yes, then
    `confirm_reservation`.
16. **Party size over the limit.** Ask for a table for 10. Expect: it says parties over 6
    need a human, doesn't attempt `hold_slot`.
17. **Out of hours / past date.** Ask for a table "yesterday" or at "2 AM". Expect: it
    explains the hours/window rather than calling a tool that will just error.
18. **No tables available.** *Setup:* book out every table for a specific date/time first
    (e.g. via the `/docs` Swagger UI, `POST /reservations/hold` ten times for the same
    slot with party_size varying to hit all 10 tables). Then ask for that exact slot in the
    CLI. Expect: it says nothing's free and offers to try another time, doesn't fabricate a
    table.
19. **Lookup by phone.** After booking, say "what's the status of my reservation" and give
    the phone number used. Expect: `lookup_reservation` is called and it reads back the
    correct one.
20. **Cancel a reservation.** After booking and confirming, say "actually cancel that."
    Expect: `cancel_reservation` runs, and a follow-up lookup shows it as cancelled — this
    exercises the earlier `lookup_reservation` fix that surfaces cancelled bookings, not
    just active ones.
21. **Double-booked slot.** Book a specific table/slot to exhaustion (as in #18) in one CLI
    session, then in a second CLI session (a second terminal, new `call_id`) try the same
    slot. Expect: the second session is told nothing's available, never a silent duplicate
    booking — this is the "done when" concurrency guarantee from Phase 2, observed from the
    conversation layer rather than a raw DB test this time.
22. **Hold expiring before confirming.** *Optional, slow* - hold a slot, then wait over 5
    minutes (`HOLD_EXPIRY_MINUTES`) before saying yes to confirm. Expect: `confirm_reservation`
    reports the hold expired and asks you to check availability again, rather than silently
    confirming a stale hold.

## D. Mixed and edge cases (8)

23. **Reservation and order in one call.** "I'd like to book a table for two tonight, and
    also order some naan for delivery tomorrow." Expect: it handles both without conflating
    the reservation's party/date with the order's address/items.
24. **Changing your mind mid-flow.** While booking, after giving party size 2, say
    "actually make that four." Expect: it re-checks availability for 4, doesn't silently
    keep the old hold on a 2-seat table.
25. **Interruption with an info question.** Mid-order, ask "what time do you close?" Expect:
    it answers (from the prompt or `get_business_info`) and then returns to where the order
    left off, without losing the draft.
26. **Forced tool error.** Try to confirm an order twice in a row (say yes twice quickly), or
    ask it to confirm a reservation that was never held. Expect: the second/invalid call
    surfaces the tool's error message in plain language, not a crash or a nonsense reply.
27. **Out-of-scope request.** Ask about "takeaway pickup" or "can I get a refund." Expect:
    it says that needs a human and doesn't attempt to fake a workaround.
28. **Very short utterances.** Answer prompts tersely ("two", "yes", "560038") instead of
    full sentences. Expect: it still tracks state correctly and doesn't ask you to repeat
    yourself.
29. **Price without ordering.** Ask "how much is the chicken biryani" without adding
    anything. Expect: it answers via `search_menu` and does not accidentally call `add_item`.
30. **Cancel the whole order.** Mid-order (2+ items added, not yet confirmed), say "never
    mind, forget the whole order." Expect: `cancel_order` is called, and the next
    `get_order_summary`/readback shows nothing pending — this exercises the `cancel_order`
    tool added in this phase.

---

## What's deliberately not covered here

- Exact wording of any reply — only behavior.
- Voice-specific concerns (barge-in, endpointing, latency) — that's Phase 4+.
- Automated pass/fail — see `tests/test_agent_graph.py` for what *is* automated (tool
  wiring, error surfacing, call-sheet formatting), which is intentionally narrower than
  this list.
