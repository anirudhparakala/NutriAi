# Golden Fixtures - Smoke Test Images

This folder contains reference images with expected nutritional outcomes for regression testing.

## Test Categories

### 1. Fries Size Variance
- `mcdonalds_fries_small.jpg` → Expected: ~71g, ~230 kcal
- `mcdonalds_fries_medium.jpg` → Expected: ~111g, ~350 kcal
- `mcdonalds_fries_large.jpg` → Expected: ~154g, ~490 kcal

**Goal**: Verify portion resolver produces stable gram estimates across sizes.

### 2. Beverage Variants (Diet vs Regular)
- `cola_diet.jpg` → Expected: <5 kcal/100g, <1g carbs/100g
- `cola_regular.jpg` → Expected: ~42 kcal/100g, ~10.5g carbs/100g

**Goal**: Verify USDA matching + sanity gate catches diet/zero qualifiers.

### 3. Milk Fat Percentages
- `milk_skim.jpg` → Expected: ~0.1-0.6g fat/100g
- `milk_1percent.jpg` → Expected: ~0.4-1.3g fat/100g
- `milk_2percent.jpg` → Expected: ~0.9-2.4g fat/100g
- `milk_whole.jpg` → Expected: ≥3.0g fat/100g

**Goal**: Verify nutrition sanity gate validates fat content matches % marker.

### 4. Ground Meat Leanness
- `ground_beef_80lean.jpg` → Expected: ~20g fat/100g
- `ground_beef_90lean.jpg` → Expected: ~10g fat/100g

**Goal**: Verify sanity gate validates fat ≈ (100 - lean%) ± 3g.

### 5. Cuisine Diversity (Biryani/Curry/Kebab)
- `chicken_biryani.jpg` → Expected: chicken, rice, ghee detected
- `paneer_tikka_masala.jpg` → Expected: paneer, cream/butter identified
- `seekh_kebab.jpg` → Expected: ground meat, spices

**Goal**: Verify USDA matching doesn't drift across non-Western cuisines.

### 6. Smoothie/Protein Shake
- `protein_shake_labeled.jpg` → Expected: Vision reads grams from label
- `smoothie_mixed.jpg` → Expected: Portion labels for unlabeled items

**Goal**: Verify vision-stated grams are preserved when visible.

### 7. Multi-Photo Scenarios
- `burger_angle1.jpg` + `burger_angle2.jpg` → Same meal, different views
- `meal_tray_full.jpg` + `meal_drink_closeup.jpg` → Union of items

**Goal**: Verify multi-photo handling doesn't double-count.

### 8. Sweet Potato vs Regular Fries
- `french_fries_regular.jpg` → Should NOT match "sweet potato fries"
- `sweet_potato_fries.jpg` → Should match sweet potato

**Goal**: Verify IDF penalties prevent "fries" → "sweet potato fries" drift.

## Running Tests

```bash
# Manual visual inspection (MVP)
streamlit run ui/app.py
# Upload each image, verify outcomes match expected ranges

# Future: Automated test suite
python tests/test_golden_fixtures.py
```

## Expected Stability Metrics

After fixes, we should see:
- **Portion resolver**: >80% tier 1-2 (user/vision/brand-size), <20% heuristics
- **USDA strategies**: >60% strategy 1 (exact query), <10% strategy 3
- **Sanity gate**: <5% failures (only on genuinely ambiguous items)
- **Calorie variance**: <10% between runs for same image + same answers

## Adding New Fixtures

When adding new test images:
1. Use clear, well-lit photos
2. Include brand/packaging when relevant
3. Document expected macros in filename or companion `.json`
4. Test edge cases that broke before (e.g., tofu/cola confusion)
