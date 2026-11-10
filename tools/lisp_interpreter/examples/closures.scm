; Recursion, closures and a higher-order procedure.
(define fact
  (lambda (n)
    (if (<= n 1)
        1
        (* n (fact (- n 1))))))

(define make-adder
  (lambda (n)
    (lambda (x) (+ x n))))

(define add5 (make-adder 5))

(define squares (map (lambda (x) (* x x)) (list 1 2 3 4)))

(begin
  (fact 10)
  (add5 37)
  squares)
