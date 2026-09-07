// overload 0
ARRAY TEXT($arr1;0)
var $v2 : Date
var $v3 : Time
METHOD GET MODIFICATION DATE($arr1;$v2;$v3;*)
// overload 0 flag-sweep omit-trailing-from:*
ARRAY TEXT($arr4;0)
var $v5 : Date
var $v6 : Time
METHOD GET MODIFICATION DATE($arr4;$v5;$v6)
// overload 0 union-sweep path=Text
var $v7 : Date
var $v8 : Time
METHOD GET MODIFICATION DATE("synthText";$v7;$v8;*)
// overload 0 union-sweep path=Text array
ARRAY TEXT($arr9;0)
var $v10 : Date
var $v11 : Time
METHOD GET MODIFICATION DATE($arr9;$v10;$v11;*)
// overload 0 union-sweep modDate=Date
ARRAY TEXT($arr12;0)
var $v13 : Date
var $v14 : Time
METHOD GET MODIFICATION DATE($arr12;$v13;$v14;*)
// overload 0 union-sweep modDate=Date array
ARRAY TEXT($arr15;0)
ARRAY DATE($arr16;0)
var $v17 : Time
METHOD GET MODIFICATION DATE($arr15;$arr16;$v17;*)
// overload 0 union-sweep modTime=Time
ARRAY TEXT($arr18;0)
var $v19 : Date
var $v20 : Time
METHOD GET MODIFICATION DATE($arr18;$v19;$v20;*)
// overload 0 union-sweep modTime=Integer array
ARRAY TEXT($arr21;0)
var $v22 : Date
ARRAY INTEGER($arr23;0)
METHOD GET MODIFICATION DATE($arr21;$v22;$arr23;*)
