// Writes raw bytes (relocations applied) of [addr, addr+n) to a file.  args: addr n outfile
import ghidra.app.script.GhidraScript;
public class DumpBytes extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs(); var addr = toAddr(a[0]); int n = Integer.parseInt(a[1]);
        byte[] buf = new byte[n]; currentProgram.getMemory().getBytes(addr, buf);
        java.nio.file.Files.write(java.nio.file.Path.of(a[2]), buf);
        println("wrote " + n);
    }
}
