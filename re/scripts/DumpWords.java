// Dumps n 16-bit words from addr (relocations applied).  args: addr n
import ghidra.app.script.GhidraScript;
public class DumpWords extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs(); var addr = toAddr(a[0]); int n = Integer.parseInt(a[1]);
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < n; i++) { b.append(String.format("%04x ", getShort(addr.add(2 * i)) & 0xffff)); if (i % 16 == 15) { println(addr.add(2 * (i - 15)) + ": " + b); b.setLength(0); } }
    }
}
