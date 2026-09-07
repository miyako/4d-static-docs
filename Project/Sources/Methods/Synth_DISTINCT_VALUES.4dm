// overload 0
ARRAY LONGINT($arr1;0)
ARRAY INTEGER($arr2;0)
DISTINCT VALUES([SynthTable]label;$arr1;$arr2)
// overload 0 union-sweep countArray=Integer array
ARRAY LONGINT($arr3;0)
ARRAY INTEGER($arr4;0)
DISTINCT VALUES([SynthTable]label;$arr3;$arr4)
// overload 0 union-sweep countArray=Real array
ARRAY LONGINT($arr5;0)
ARRAY REAL($arr6;0)
DISTINCT VALUES([SynthTable]label;$arr5;$arr6)
