# Spec: Saffron & Seoul (one-page)

A cafe serving Indian, Korean and continental food. One branch (Bengaluru), phone agent handles **table booking** and **delivery orders** only.

## Basics

- Timezone: store UTC, show `Asia/Kolkata`.
- Opening hours: every day, 11:00 to 23:00. Last order 22:30. Last reservation start 21:30.
- Phone/reservation names are collected by the agent; caller ID fills the phone number later (Phase 6).

## Tables (10)

| Table | Seats | Count |
|---|---|---|
| T1-T4 | 2 | 4 |
| T5-T8 | 4 | 4 |
| T9-T10 | 6 | 2 |

- Reservation length: 90 minutes. Slots start on 30-minute marks.
- Party size 1-6 (bigger parties: transfer to human, out of scope for the agent).
- Booking up to 14 days ahead. A hold expires after 5 minutes.
- Party size picks the smallest free table that fits.

## Delivery

- Area: within 5 km of the cafe (a fixed list of pincodes in the DB).
- Cash on delivery only. No online payment.
- Minimum order Rs 250. Delivery fee Rs 40, free above Rs 700.
- Estimated time quoted: 40 minutes.

## Out of scope

Takeaway pickup, payments, loyalty, complaints/refunds, events/catering, parties over 6, changing an order after it is confirmed (transfer to human).

## Latency target

End of caller speech to first agent audio: about **1 second** (p50), under 1.5 s (p95). Stage budgets are in the plan, Phase 7.

## Menu (30 items)

Prices in Rs. Veg = V, non-veg = N. Spice levels apply to items marked S.

### Indian

| # | Item | Type | Price | Aliases (for search) |
|---|---|---|---|---|
| 1 | Paneer Butter Masala | V | 320 | paneer makhani |
| 2 | Palak Paneer | V | 300 | saag paneer |
| 3 | Dal Makhani | V | 260 | black dal |
| 4 | Butter Chicken | N | 380 | murgh makhani |
| 5 | Chicken Biryani | N | 350 | murg biryani |
| 6 | Veg Biryani | V | 280 | vegetable biryani |
| 7 | Butter Naan | V | 60 | naan |
| 8 | Garlic Naan | V | 75 | |
| 9 | Jeera Rice | V | 150 | |
| 10 | Samosa (2 pcs) | V | 90 | samose |

### Korean

| # | Item | Type | Price | Aliases |
|---|---|---|---|---|
| 11 | Bibimbap (Veg) | V | 340 | bibimbap |
| 12 | Chicken Bibimbap | N | 390 | |
| 13 | Kimchi Fried Rice | V | 310 | kimchi rice |
| 14 | Korean Fried Chicken (6 pcs) | N | 420 | kfc, kfc chicken |
| 15 | Tteokbokki | V | 330 | topokki, spicy rice cakes |
| 16 | Japchae | V | 360 | glass noodles |
| 17 | Kimchi Jjigae | N | 400 | kimchi stew |
| 18 | Korean Corn Dog | V | 220 | |
| 19 | Mandu (6 pcs) | V | 280 | korean dumplings, dumplings |
| 20 | Bulgogi Rice Bowl | N | 430 | bulgogi |

### Continental

| # | Item | Type | Price | Aliases |
|---|---|---|---|---|
| 21 | Margherita Pizza | V | 380 | pizza margherita |
| 22 | Pepperoni Pizza | N | 460 | |
| 23 | White Sauce Pasta | V | 340 | alfredo pasta |
| 24 | Arrabbiata Pasta | V | 330 | red sauce pasta |
| 25 | Grilled Chicken Burger | N | 350 | chicken burger, burger |
| 26 | Veggie Burger | V | 290 | veg burger, burger |
| 27 | Caesar Salad | V | 300 | |
| 28 | French Fries | V | 160 | fries |

### Drinks and dessert

| # | Item | Type | Price | Aliases |
|---|---|---|---|---|
| 29 | Masala Chai | V | 90 | chai |
| 30 | Iced Americano | V | 180 | |
| 31 | Mango Lassi | V | 150 | lassi |
| 32 | Brownie with Ice Cream | V | 240 | brownie |

(32 items: a couple more than 30 so drinks and dessert exist for the tests.)

## Modifiers

| Modifier | Applies to | Extra cost |
|---|---|---|
| Spice level: mild / medium / hot | items 1, 4, 5, 15, 17, 14, 24 | 0 |
| No onion / no garlic | Indian items (1-6) | 0 |
| Extra cheese | pizzas, burgers, pasta | 40 |
| Extra kimchi | items 11, 12, 13, 17 | 30 |
| Add fried egg | items 11, 12, 13, 20 | 30 |
| Extra ice / less ice | drinks 30, 31 | 0 |
| Less sugar | items 29, 31, 32 | 0 |
| Boneless | items 4, 14 | 40 |

## Sold-out demo

Menu manager (Phase 5) can flip `is_available`. Good demo targets: Butter Chicken, Tteokbokki.

## Test hooks (used by Phase 2/3 tests)

- "matar paneer" -> not found, nearest: Palak Paneer / Paneer Butter Masala.
- "burger" -> near match, two options (chicken / veggie).
- "list continental items" -> items 21-28.
- "actually remove the burger" -> order edit.
