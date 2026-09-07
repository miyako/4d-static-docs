// overload 0
DELETE INDEX(Nil;*)
// overload 0 flag-sweep omit-trailing-from:*
DELETE INDEX(Nil)
// overload 0 union-sweep fieldPtr=Pointer
DELETE INDEX(Nil;*)
// overload 0 union-sweep fieldPtr=Text
DELETE INDEX("synthText";*)
// overload 1
DELETE INDEX(Nil;*)
// overload 1 flag-sweep omit-trailing-from:*
DELETE INDEX(Nil)
// overload 1 union-sweep indexName=Pointer
DELETE INDEX(Nil;*)
// overload 1 union-sweep indexName=Text
DELETE INDEX("synthText";*)
