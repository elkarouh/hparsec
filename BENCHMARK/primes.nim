import math, nimpy, strformat
let time = pyImport("time")

var N = 1000000

proc is_prime(n: int): bool =
    var result = true
    for k in 2 ..< int(pow(float(n), 0.5)) + 1:
        if n mod k == 0:
            result = false
            break
    return result

proc count_primes(n: int): int =
    var count = 0
    for k in 2 ..< n:
        if is_prime(k):
            count += 1

    return count

var start = time.perf_counter()
echo(fmt"Number of primes: {count_primes(N)}")
echo(fmt"time elapsed: {time.perf_counter() - start}/s")
