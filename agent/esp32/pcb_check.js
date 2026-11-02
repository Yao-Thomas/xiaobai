var comps = await eda.pcb_PrimitiveComponent.getAll();
var result = '';
for (var i = 0; i < comps.length; i++) {
  var c = comps[i];
  if (!c.designator) continue;
  result = result + c.designator + ' x' + c.x + ' y' + c.y + '\n';
}
return result;
