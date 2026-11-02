var comps = await eda.sch_PrimitiveComponent.getAll();
var list = [];
for (var i = 0; i < comps.length; i++) {
  var c = comps[i];
  if (!c.designator || c.designator.length === 0) continue;
  list.push(c.designator + ' | ' + (c.name || '-') + ' | x=' + c.x + ' | y=' + c.y);
}
list.sort();
return list.join('\n');
