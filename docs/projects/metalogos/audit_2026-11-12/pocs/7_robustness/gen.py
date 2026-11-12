# Generates the deep-input files (too large to ship). Run: python3 gen.py && mlog check deep_plus.mlog
tail = '\nflow Main { input: String = "x" -> P -> output }\n'
open('deep_plus.mlog','w').write('pattern P(x: String) -> String { let a = ' + '+'.join(['"a"']*50000) + ' return a }' + tail)
open('deep_if.mlog','w').write('pattern P(x: String) -> String { ' + 'if x == "x" then { '*3000 + 'print("a")' + ' }'*3000 + ' return "ok" }' + tail)
