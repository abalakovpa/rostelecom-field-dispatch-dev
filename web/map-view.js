import {icon} from './icons.js';
import * as maplibregl from './vendor/maplibre-gl.js';
import {routeFeatures,boundsOf} from './map-data.js';

maplibregl.setWorkerUrl(new URL('./vendor/maplibre-gl-worker.js',import.meta.url).href);

export class MapView{
  constructor(target,{onTileError,onTileLoad,onError}){
    this.groups={orders:[],centers:[],route:[]};this.routeData=routeFeatures([]);
    this.map=new maplibregl.Map({container:target,center:[60.605,56.84],zoom:10,maxZoom:19,
      attributionControl:false,dragRotate:false,pitchWithRotate:false,
      style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize:256,maxzoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}},
        layers:[{id:'osm',type:'raster',source:'osm'}]}});
    this.map.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');
    this.map.addControl(new maplibregl.AttributionControl({compact:false}),'bottom-right');
    this.map.touchZoomRotate.disableRotation();
    this.map.on('load',()=>{
      this.ready=true;
      this.map.addSource('route',{type:'geojson',data:this.routeData});
      this.map.addLayer({id:'route-casing',type:'line',source:'route',layout:{'line-cap':'round','line-join':'round'},
        paint:{'line-color':'#ffffff','line-width':5,'line-opacity':.95,'line-dasharray':[1.2,1.4]}});
      this.map.addLayer({id:'route-color',type:'line',source:'route',layout:{'line-cap':'round','line-join':'round'},
        paint:{'line-color':['get','color'],'line-width':2.5,'line-opacity':.95,'line-dasharray':[2.4,2.8]}});
      this.map.on('mousemove','route-color',event=>{
        const feature=event.features?.[0];if(!feature)return;
        this.tooltip??=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:10,className:'route-tooltip'});
        this.tooltip.setLngLat(event.lngLat).setText(feature.properties.label).addTo(this.map);
        this.map.getCanvas().style.cursor='pointer';
      });
      this.map.on('mouseleave','route-color',()=>{this.tooltip?.remove();this.map.getCanvas().style.cursor='';});
    });
    this.map.on('error',event=>{if(event.sourceId==='osm')onTileError();else onError();});
    this.map.on('sourcedata',event=>{if(event.sourceId==='osm'&&event.isSourceLoaded)onTileLoad();});
  }
  clearMarkers(group){
    for(const marker of this.groups[group])marker.remove();this.groups[group]=[];
    if(this.popupGroup===group)this.closePopup();
  }
  marker(group,{lat,lon,className,text,title,popup,zIndex=0}){
    const element=document.createElement('button');element.type='button';element.className='map-marker '+className;
    if(group==='centers')element.append(icon('house'));else element.textContent=text;
    element.title=title;element.setAttribute('aria-label',title);element.style.zIndex=String(zIndex);
    const marker=new maplibregl.Marker({element,anchor:'center'}).setLngLat([lon,lat]).addTo(this.map);
    element.addEventListener('click',event=>{
      event.stopPropagation();this.closePopup();this.popupGroup=group;
      this.popup=new maplibregl.Popup({offset:18,maxWidth:'260px',focusAfterOpen:false})
        .setLngLat([lon,lat]).setDOMContent(popup).addTo(this.map);
    });
    this.groups[group].push(marker);return marker;
  }
  closePopup(){this.popup?.remove();this.popup=null;this.popupGroup=null;}
  resize(){this.map.resize();}
  focus(position,zoom){this.map.easeTo({center:position,zoom,duration:600});}
  fitPoints(points,maxZoom=14,padding=45){
    const bounds=boundsOf(points);if(bounds)this.map.fitBounds(bounds,{padding,maxZoom,duration:350});
  }
  showCity(){
    this.map.fitBounds([[60.40,56.68],[60.85,57.00]],{padding:35,maxZoom:11,duration:350});
  }
  clearRoute(){
    this.clearMarkers('route');this.tooltip?.remove();this.routeData=routeFeatures([]);
    this.map.getSource('route')?.setData(this.routeData);
  }
  showRoute(segments){
    this.routeData=routeFeatures(segments);this.map.getSource('route')?.setData(this.routeData);
    this.fitPoints(this.routeData.features.flatMap(f=>f.geometry.coordinates),16,35);
  }
}
