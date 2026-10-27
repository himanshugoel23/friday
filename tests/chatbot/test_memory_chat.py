async def test_chat_lists_memory_and_forgets_an_item(chat):
    from friday.core.models import Place

    await chat.onboard()
    user = await chat.user()
    await chat.c.repos.places.upsert(Place(owner_user_id=user.id, label="Shreya Salon",
                                           aliases=["shriya salon"]))
    out = await chat.say("what do you remember about me")
    text = " ".join(m.text for m in out)
    assert "Shreya Salon" in text and "shriya salon" in text.lower()
    out = await chat.say("forget shriya salon")
    assert out and any("bhool" in m.text.lower() for m in out)
    place = (await chat.c.repos.places.list_for_owner(user.id))[0]
    assert place.aliases == []
