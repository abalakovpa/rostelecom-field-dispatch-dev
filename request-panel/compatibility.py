def work_fits_building(building,work):
    code=work['code']
    if code=='INST_PON_MKD':return building['building_type']=='MKD' and building['technology']=='PON'
    if code=='INST_FTTB_MKD':return building['building_type']=='MKD' and building['technology']=='FTTB'
    if code=='INST_PRIVATE_VLS':return building['building_type']=='PRIVATE' and building.get('overhead_line',False)
    if code=='SURVEY_PRIVATE':return building['building_type']=='PRIVATE'
    return True
