package io.github.deskit_app.deskit

/**
 * Which rows are this very phone (2026-11-28): the mark and the choice of rows to
 * forget, with nothing of Android's in them. Run from CryptChecks' main, with its
 * counter, so `gradle jvmChecks` is one run and one exit code.
 */
internal fun samePhoneChecks(check: (String, Boolean) -> Unit) {
    val uid = "11111111-2222-4333-8444-555555555555"
    val id = "9f3c2b1a7d6e5f40"
    val mine = SamePhone.mark(uid, id)

    // ---- the mark ----
    // sha256("deskit/same-phone/v1" NUL uid NUL id), its first 32 hex, by Python's hashlib
    check("the mark is the hash it says it is, got $mine", mine == "ddc865a6561ba03cd90fd2803da1d111")
    check("the same phone and account, the same mark: a later install reads as this one",
          mine == SamePhone.mark(uid, id))
    check("however Android spells the id", mine == SamePhone.mark(uid, " 9F3C2B1A7D6E5F40 "))
    check("another phone, another mark", mine != SamePhone.mark(uid, "9f3c2b1a7d6e5f41"))
    check("another account on this phone, another mark",
          mine != SamePhone.mark("99999999-2222-4333-8444-555555555555", id))
    check("the id itself is not in it", !mine.contains(id.take(8)))
    for (none in listOf(null, "", "   ", "abc", "9774d56d682e549c", "0000000000000000", "unknown", "null")) {
        check("what is no id ('$none') makes no mark", SamePhone.mark(uid, none) == "")
    }
    check("no account, no mark", SamePhone.mark("", id) == "")

    // ---- the rows to forget ----
    val other = SamePhone.mark(uid, "1111222233334444")
    val me = "aaaaaaaa-0000-4000-8000-000000000001"
    val before = "aaaaaaaa-0000-4000-8000-000000000002"
    val longBefore = "aaaaaaaa-0000-4000-8000-000000000006"
    val rows = listOf(
        SamePhone.Row(me, true, mine),
        SamePhone.Row(before, true, mine),                                           // the install before this one
        SamePhone.Row("aaaaaaaa-0000-4000-8000-000000000003", true, other),          // another phone of his
        SamePhone.Row("aaaaaaaa-0000-4000-8000-000000000004", true, ""),             // a row from before the mark
        SamePhone.Row("aaaaaaaa-0000-4000-8000-000000000005", false, mine),          // a PC, whatever it says
        SamePhone.Row(longBefore, true, mine),                                       // and the one before that
        SamePhone.Row("", true, mine))                                               // a row with no id
    check("every earlier install of this phone, and nothing else",
          SamePhone.earlier(me, mine, rows) == listOf(before, longBefore))
    check("never itself", me !in SamePhone.earlier(me, mine, rows))
    check("a phone with no mark forgets nobody", SamePhone.earlier(me, "", rows).isEmpty())
    check("not even the rows that carry none either",
          SamePhone.earlier(me, "", listOf(SamePhone.Row(before, true, ""))).isEmpty())
    check("a mark cut short is no mark", SamePhone.earlier(me, mine.take(8), rows).isEmpty())
    check("a phone that does not know its own id forgets nobody",
          SamePhone.earlier("", mine, rows).isEmpty())
    check("alone on the account, nothing to forget",
          SamePhone.earlier(me, mine, listOf(SamePhone.Row(me, true, mine))).isEmpty())
}
