// Prints n far pointers (offset, segment) starting at an address: args addr n
import ghidra.app.script.GhidraScript;
public class ReadWords extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        var addr = toAddr(a[0]); int n = Integer.parseInt(a[1]);
        for (int i = 0; i < n; i++) {
            int off = getShort(addr.add(4 * i)) & 0xffff, seg = getShort(addr.add(4 * i + 2)) & 0xffff;
            var f = getFunctionAt(toAddr(String.format("%04x:%04x", seg, off)));
            println(String.format("+%02x  %04x:%04x  %s", 4 * i, seg, off, f == null ? "" : f.getName()));
        }
    }
}
