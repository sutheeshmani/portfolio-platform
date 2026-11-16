import { decimal, money, signedMoney, quantity, percent, sign, age } from "../src/lib/format.ts";
const cases: [string, string][] = [
  [decimal("1200.00000000")!, "1,200.00"],
  [decimal("1234567.005")!, "1,234,567.01"],
  [decimal("-10.004")!, "−10.00"],
  [decimal("-0.004")!, "0.00"],
  [decimal("0E-8")!, "0.00"],
  [decimal("1E+3")!, "1,000.00"],
  [decimal("4.5E+3")!, "4,500.00"],
  [decimal("1.5E-3", 4)!, "0.0015"],
  [money("1760.0000", "AUD"), "A$1,760.00"],
  [money("-1600", "USD"), "−US$1,600.00"],
  [money(null), "—"],
  [signedMoney("190"), "+A$190.00"],
  [signedMoney("-71.5"), "−A$71.50"],
  [quantity("60.00000000"), "60"],
  [quantity("1.12345678"), "1.12345678"],
  [quantity("1000"), "1,000"],
  [percent("0.5454545454545454545454545455"), "54.5%"],
  [percent("1"), "100.0%"],
  [percent("0.0049"), "0.5%"],
  [String(sign("0.00000000")), "0"],
  [String(sign("-3")), "-1"],
  [age(new Date(Date.now() - 5 * 60000).toISOString()), "5 min ago"],
];
declare const process: { exit(code: number): never };
let bad = 0;
for (const [got, want] of cases) if (got !== want) { bad++; console.log("FAIL", JSON.stringify(got), "want", JSON.stringify(want)); }
console.log(bad ? `${bad} failed` : `all ${cases.length} passed`);
if (bad) process.exit(1);
