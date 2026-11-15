export function workFitsBuilding(building,work){
 if(!building||!work)return false;
 if(work.code==='INST_PON_MKD')return building.building_type==='MKD'&&building.technology==='PON';
 if(work.code==='INST_FTTB_MKD')return building.building_type==='MKD'&&building.technology==='FTTB';
 if(work.code==='INST_PRIVATE_VLS')return building.building_type==='PRIVATE'&&building.overhead_line===true;
 if(work.code==='SURVEY_PRIVATE')return building.building_type==='PRIVATE';
 return true;
}
export function employeeFitsOrder(person,building,work,demand){
 if(!workFitsBuilding(building,work))return false;
 const height=work.code==='INST_PRIVATE_VLS'||(building.building_type==='PRIVATE'&&building.overhead_line);
 const equipment=demand??{ONT:building.technology==='PON'?1:0,ROUTER:1,STB:0};
 return person.profiles.some(p=>work.profiles.includes(p))&&person.technologies.includes(building.technology)&&(!height||person.height_permit)&&Object.entries(equipment).every(([kind,count])=>(person.equipment_capacity?.[kind]??0)>=count);
}
