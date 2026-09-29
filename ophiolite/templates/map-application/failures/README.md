# Deliberate refusal examples

`make test` asserts the refusals: a foreign Origin or Host, a missing or wrong proof, GET and preflight calls,
oversized bodies, and an expired sign-in (the page says to run `ophiolite login`). A map only reads: the tests
also assert that nothing was written.
