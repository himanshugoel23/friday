from __future__ import annotations


async def test_hi_gets_the_intro_with_consent_buttons(chat):
    out = await chat.say("hi")
    assert len(out) == 1
    assert [b.title for b in out[0].buttons] == ["Haan, theek hai", "Details", "Nahi"]
    print(chat.all_out())


async def test_full_flow_prints(chat):
    await chat.onboard()
    print(chat.all_out())
    print(await chat.say("menu"))
