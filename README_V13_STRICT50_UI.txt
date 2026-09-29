V13 Strict50 + compact review UI

- < 50% verified real discount => review chat.
- >= 50% verified real discount => ultra group.
- exceptional/anomalous verified prices => ultra group with score priority 99.
- removes verification/time/screenshot-explanation blocks from Telegram captions.
- product screenshots hide Amazon navigation and capture the product area first.
- ultra-group posts no longer show publish/reject buttons because they are already
  delivered directly to the group.
- normal review messages retain review controls pending V13 callback migration.
- effective/coupon price is hidden from the caption if it implies >60% coupon
  reduction, avoiding obviously bad coupon display math.
