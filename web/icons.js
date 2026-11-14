// Consistent local line icons; no CDN, font glyphs or runtime dependency.
const paths={
 map:['m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z','M9 3v15M15 6v15'],
 timeline:['M4 4v16h16','M8 7h9M8 11h6M12 15h8'],
 bell:['M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9','M10 21h4'],
 search:['m21 21-5-5','M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z'],
 refresh:['M20 7v5h-5','M4 17v-5h5','M6.1 6.1A8 8 0 0 1 19.9 10M17.9 17.9A8 8 0 0 1 4.1 14'],
 locate:['M12 2v3M12 19v3M2 12h3M19 12h3','M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z','M12 9v6M9 12h6'],
 house:['m3 10 9-7 9 7','M5 9v12h14V9','M9 21v-7h6v7'],
 menu:['M4 6h16M4 12h16M4 18h16'],
 x:['m6 6 12 12M6 18 18 6'],
};
export function icon(name){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 for(const [key,value]of Object.entries({viewBox:'0 0 24 24',width:'18',height:'18',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
 svg.classList.add('ui-icon');
 for(const d of paths[name]||[]){const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path);}
 return svg;
}
export function applyIcons(root=document){
 for(const target of root.querySelectorAll('[data-icon]'))target.replaceChildren(icon(target.dataset.icon));
}
