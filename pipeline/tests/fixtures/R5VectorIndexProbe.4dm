// Compile only: these call sites do not establish runtime field/index applicability.
ARRAY POINTER($fieldPointers;1)
$fieldPointers{1}:=->[SynthTable]label
CREATE INDEX([SynthTable];$fieldPointers;Vector cosine index;"cosine")
CREATE INDEX([SynthTable];$fieldPointers;Vector dot index;"dot")
CREATE INDEX([SynthTable];$fieldPointers;Vector euclidean index;"euclidean")
SET INDEX([SynthTable]label;Vector cosine index)
SET INDEX([SynthTable]label;Vector dot index)
SET INDEX([SynthTable]label;Vector euclidean index)
