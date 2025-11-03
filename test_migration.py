"""Test script for database migration to schema version 5."""

from integrations import db

print("Testing Database Migration 5...")
print("=" * 50)

# Initialize database (will run migration if needed)
db.init()

print("\nTesting user_settings helper functions...")
print("-" * 50)

# Test set_user_setting
db.set_user_setting("body_weight_kg", "79.8")
db.set_user_setting("height_cm", "182.88")
db.set_user_setting("calorie_goal", "2500")

# Test get_user_setting
weight = db.get_user_setting("body_weight_kg")
height = db.get_user_setting("height_cm")
goal = db.get_user_setting("calorie_goal")

print(f"\n✅ Retrieved settings:")
print(f"   Body Weight: {weight} kg")
print(f"   Height: {height} cm")
print(f"   Calorie Goal: {goal} kcal")

# Test updating existing setting
db.set_user_setting("body_weight_kg", "80.0")
updated_weight = db.get_user_setting("body_weight_kg")
print(f"\n✅ Updated weight: {updated_weight} kg")

# Test non-existent setting
missing = db.get_user_setting("non_existent_key")
print(f"\n✅ Non-existent key returns: {missing}")

print("\n" + "=" * 50)
print("✅ Migration 5 test complete!")
