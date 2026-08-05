property isTokenizerLoaded : Boolean

shared singleton Class constructor
	
	This:C1470.isTokenizerLoaded:=False:C215
	
shared Function loadTokenizer($modelFile : 4D:C1709.File)
	
	If ($modelFile#Null:C1517) || (OB Instance of:C1731($modelFile; 4D:C1709.File)) || ($modelFile.exists)
		If (Not:C34(This:C1470.isTokenizerLoaded))
			Extract SET OPTION(Extract Option Tokenizer File; $modelFile)
			This:C1470.isTokenizerLoaded:=True:C214
		End if 
	End if 