from friday.simworld import load_world


def test_world_loads_and_phones_unique():
    world = load_world()
    phones = [b.phone for b in world.businesses]
    assert len(phones) == len(set(phones))
    care = world.by_phone("+911800000121")
    assert care and care.is_customer_care and "root" in care.persona.ivr
    assert any(b.scam for b in world.businesses)
    assert any(b.hotel for b in world.businesses)
