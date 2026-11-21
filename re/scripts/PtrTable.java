// Reads far pointers backwards/forwards from addr; prints index, target, and target C-string.  args: start_addr count
import ghidra.app.script.GhidraScript;
public class PtrTable extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        var addr = toAddr(a[0]); int n = Integer.parseInt(a[1]);
        for (int i = 0; i < n; i++) {
            int off = getShort(addr.add(4 * i)) & 0xffff, seg = getShort(addr.add(4 * i + 2)) & 0xffff;
            String s = "";
            if (seg == 0x1290) { var t = toAddr(String.format("1290:%04x", off)); StringBuilder b = new StringBuilder();
                for (int k = 0; k < 40; k++) { int c = getByte(t.add(k)) & 0xff; if (c == 0) break; b.append((char) c); } s = b.toString(); }
            println(String.format("%3d  %s  %04x:%04x  %s", i, addr.add(4 * i), seg, off, s));
        }
    }
}
