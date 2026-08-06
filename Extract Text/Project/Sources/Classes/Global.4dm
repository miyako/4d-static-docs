property _modelName : Text
property isTokenizerLoaded : Boolean
property max_position_embeddings : Integer
property prefix : Text
property modelFile : 4D:C1709.File
property dimensions : Integer
property pooling_mode : Integer

shared singleton Class constructor
	
	This:C1470.isTokenizerLoaded:=False:C215
	This:C1470._modelName:=""
	
shared Function get modelName() : Text
	
	return This:C1470._modelName
	
shared Function set modelName($modelName : Text)
	
	If (This:C1470._modelName="")
		This:C1470._modelName:=$modelName
	End if 
	
shared Function loadTokenizer($modelFile : 4D:C1709.File)
	
	If ($modelFile#Null:C1517) || (OB Instance of:C1731($modelFile; 4D:C1709.File)) || ($modelFile.exists)
		If (Not:C34(This:C1470.isTokenizerLoaded))
			Extract SET OPTION(Extract Option Tokenizer File; $modelFile)
			This:C1470.isTokenizerLoaded:=True:C214
		End if 
	End if 