var $llama : cs:C1710.llama.llama
var $homeFolder : 4D:C1709.Folder
$homeFolder:=Folder:C1567(fk home folder:K87:24).folder(".GGUF")

var $port : Integer

var $event : cs:C1710.event.event
$event:=cs:C1710.event.event.new()

$event.onError:=Formula:C1597(ALERT:C41($2.message))
//$event.onSuccess:=Formula(ALERT($2.models.extract("name").join(",")+" loaded!"))
$event.onData:=Formula:C1597(LOG EVENT:C667(Into 4D debug message:K38:5; This:C1470.file.fullName+":"+String:C10((This:C1470.range.end/This:C1470.range.length)*100; "###.00%")))
$event.onData:=Formula:C1597(MESSAGE:C88(This:C1470.file.fullName+":"+String:C10((This:C1470.range.end/This:C1470.range.length)*100; "###.00%")))
$event.onResponse:=Formula:C1597(LOG EVENT:C667(Into 4D debug message:K38:5; This:C1470.file.fullName+":download complete"))
$event.onResponse:=Formula:C1597(MESSAGE:C88(This:C1470.file.fullName+":download complete"))
$event.onTerminate:=Formula:C1597(LOG EVENT:C667(Into 4D debug message:K38:5; (["process"; $1.pid; "terminated!"].join(" "))))

var $folder : 4D:C1709.Folder
var $path; $mmproj; $cache_type_k; $cache_type_v : Text
var $n_gpu_layers; $threads; $batches; $ubatch_size; \
$threads_batch; $batch_size; $max_position_embeddings : Integer

$n_gpu_layers:=99

var $iniFile : 4D:C1709.File
var $ini : Collection

$ini:=[]
$ini.push("version = 1")

/*
$ini.push("[LFM2.5-Embedding-350M]")
$ini.push("model = "+$homeFolder.file("LiquidAI/LFM2.5-Embedding-350M-Q8_0.gguf").path)
$ini.push("pooling = cls")
$max_position_embeddings:=30000
*/
$ini.push("[bge-m3]")
$ini.push("model = "+$homeFolder.file("bge-m3/bge-m3-Q8_0.gguf").path)
$ini.push("pooling = cls")
$max_position_embeddings:=8192

$port:=8080
$folder:=$homeFolder.folder("llama-"+String:C10($port))

$iniFile:=$folder.file("models.ini")
$iniFile.setText($ini.join("\n"))


$batch_size:=$max_position_embeddings
$ubatch_size:=$max_position_embeddings

$batches:=4
$threads:=4
$threads_batch:=4

var $logFile : 4D:C1709.File
$logFile:=$folder.file("llama.log")
$folder.create()
If (Not:C34($logFile.exists))
	$logFile.setContent(4D:C1709.Blob.new())
End if 

var $options : Object
$options:={\
embeddings: True:C214; \
models_preset: $iniFile; \
ctx_size: $max_position_embeddings*$batches; \
batch_size: $batch_size*$batches; \
ubatch_size: $ubatch_size; \
parallel: $batches; \
threads: $threads; \
threads_batch: $threads_batch; \
threads_http: $batches+1; \
log_file: $logFile; \
log_disable: False:C215; \
n_gpu_layers: $n_gpu_layers}

$llama:=cs:C1710.llama.llama.new($port; Null:C1517; $homeFolder; $options; $event)