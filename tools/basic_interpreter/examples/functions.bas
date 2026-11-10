' Variables and single-line functions.
LET RATE = 2
DEF FN SQ(X) = X * X
DEF FN AREA(W, H) = W * H * RATE
DEF FN HYP2(A, B) = FN SQ(A) + FN SQ(B)
PRINT "square of 4:", FN SQ(4)
PRINT "area 3 x 5:", FN AREA(3, 5)
PRINT "3-4 hypotenuse squared:", FN HYP2(3, 4)
