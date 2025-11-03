"""Test script for WHOOP sync manager."""

from datetime import datetime, timedelta
from integrations.whoop_sync import WhoopSyncManager, auto_sync_on_startup

print("Testing WHOOP Sync Manager...")
print("=" * 60)

sync_manager = WhoopSyncManager()

# Test 1: Check last sync date
print("\n1. Checking last sync date...")
last_sync = sync_manager.get_last_sync_date()
print(f"   Last sync: {last_sync.date() if last_sync else 'Never'}")

# Test 2: Sync recent 7 days (smaller test)
print("\n2. Syncing last 7 days of WHOOP data...")
days_synced = sync_manager.sync_recent_days(days=7)
print(f"   Days synced: {days_synced}")

# Test 3: Sync body weight
print("\n3. Syncing body weight from WHOOP...")
weight_synced = sync_manager.sync_body_weight()

# Test 4: Get data for yesterday
print("\n4. Retrieving yesterday's WHOOP data...")
yesterday = datetime.now() - timedelta(days=1)
data = sync_manager.get_whoop_data_for_date(yesterday)

if data:
    print(f"   ✅ Retrieved data for {data['date']}:")
    print(f"      Recovery: {data['recovery_score']}%")
    print(f"      Strain: {data['strain']}")
    print(f"      Sleep Performance: {data['sleep_performance']}%")
    print(f"      HRV: {data['hrv']} ms")
    print(f"      RHR: {data['rhr']} bpm")
else:
    print(f"   ⚠️  No data found for {yesterday.date()}")

# Test 5: Get data range (last 7 days)
print("\n5. Retrieving last 7 days of WHOOP data...")
end_date = datetime.now()
start_date = end_date - timedelta(days=6)
data_range = sync_manager.get_whoop_data_range(start_date, end_date)
print(f"   Retrieved {len(data_range)} days of data")

if data_range:
    print("\n   Summary:")
    for day_data in data_range:
        recovery = day_data['recovery_score'] or 0
        strain = day_data['strain'] or 0
        print(f"   {day_data['date']}: Recovery={recovery:.0f}%, Strain={strain:.1f}")

print("\n" + "=" * 60)
print("✅ WHOOP sync manager test complete!")
print("\nTo test auto-sync on startup, uncomment the line below:")
print("# auto_sync_on_startup(days=30)")
