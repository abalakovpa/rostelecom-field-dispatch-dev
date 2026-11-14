// Route geometries come from the server; never substitute straight-line routes.
export const routeColors=['#159fe8','#20bc8b','#ef638a','#69b844','#35bbc6','#e2ac21','#6294ef','#e777b0'];
export function routeFeatures(segments){
  return {type:'FeatureCollection',features:segments.flatMap((segment,index)=>{
    const geometry=segment.geometry;
    if(geometry?.type!=='LineString'||!Array.isArray(geometry.coordinates))throw new Error('Некорректная геометрия маршрута.');
    if(geometry.coordinates.length===0)return [];
    if(geometry.coordinates.length<2||geometry.coordinates.some(p=>!Array.isArray(p)||p.length<2||!Number.isFinite(p[0])||!Number.isFinite(p[1])))throw new Error('Некорректные координаты маршрута.');
    return [{type:'Feature',properties:{color:routeColors[index%routeColors.length],label:`${segment.from_stop} → ${segment.to_stop}`},geometry}];
  })};
}
export function boundsOf(points){
  if(!points.length)return null;
  return points.reduce((box,p)=>[[Math.min(box[0][0],p[0]),Math.min(box[0][1],p[1])],
    [Math.max(box[1][0],p[0]),Math.max(box[1][1],p[1])]],[[points[0][0],points[0][1]],[points[0][0],points[0][1]]]);
}
