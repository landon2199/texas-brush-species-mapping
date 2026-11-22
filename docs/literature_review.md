# Literature review: mapping mesquite and *Prosopis* from satellites

Author: Landon Melesky

## Introduction

Mesquite (genus *Prosopis*) is a thorny, deep-rooted shrub or tree. In Texas, honey mesquite (*Prosopis glandulosa*) is native, but it has spread into former grassland. Texas Parks and Wildlife Department (TPWD) mapping found that "Native Invasive: Mesquite Shrubland" was the second most common mapped type in the state, at 6.1% of its area (Elliott et al., 2014). In East Africa and South Asia, *Prosopis juliflora* and its hybrids were planted for fuelwood and are now invasive.

This review asks three questions. How have others mapped *Prosopis* with satellite data? How did they check their accuracy? And what does this project copy, and what does it change?

Two terms come up often. A **classifier** is the model that assigns each pixel to a class. **Random Forest** (Breiman, 2001) is a classifier built from many decision trees that vote. **Overall accuracy** is the share of check points that the map labels correctly.

## How others mapped *Prosopis* and mesquite

### Africa: *Prosopis juliflora* invasion

Most satellite work on invasive *Prosopis* comes from the Horn of Africa and Kenya. These studies share one idea: use the season when *Prosopis* looks different from its neighbours. In Somaliland, *P. juliflora* stayed greener than native trees in the dry season (Meroni et al., 2017). In Afar, Ethiopia, Landsat 8 scenes were picked from the dry season, when grasses were dry and most trees except *Prosopis* had shed their leaves (Shiferaw et al., 2019).

Almost all of these studies used Random Forest. They also combined seasons. In Hargeisa, the best map used wet plus dry season Landsat 8 data (Ng et al., 2016). In Baringo, Kenya, dry and wet season Landsat scenes from 1988 to 2016 tracked *Prosopis* growth from 882 ha to 18,792 ha (Mbaabu et al., 2019). The same Kenyan area was mapped at finer scale with Sentinel-2 (10 m) and Pléiades (2 m) (Ng et al., 2017). An older study in Afar used coarse MODIS vegetation index time series with a species distribution model (Maxent) instead of a classifier (Wakie et al., 2014).

### India

The only India study that could be verified for this review is a conference paper on the Banni grassland in Kachchh, Gujarat. It mapped *Prosopis* from one 2011 Landsat 5 scene with maximum likelihood classification and reported 94.4% accuracy (Vaibhav et al., 2012). It is not a peer-reviewed journal article, and it does not say how the check points were chosen.

### Texas and the US Southwest: honey mesquite

Texas work started with aerial photos. In north Texas, hand-traced canopies on color-infrared photos showed mesquite cover rising from 14.6% to 58.7% in 20 years on untreated land (Ansley et al., 2001). A study combining 1937 aerial photos with Landsat found woody cover increases of up to 500% on rangeland that was never treated for brush (Asner et al., 2003).

Later studies compared image sizes. On 800 km² of north Texas rangeland, 1 m aerial images classified mesquite better than 30 m Landsat (94% vs. 87% overall accuracy). Landsat also overestimated mesquite cover (Mirik and Ansley, 2012). Across Oklahoma and Texas, a model trained on 1 m NAIP aerial images and driven by multi-season Landsat estimated percent woody cover with a mean absolute error of 12.1% (Hartfield and van Leeuwen, 2018). Closest to this project, drones were used to train a Random Forest on Sentinel-2 to map mesquite at three Texas sites (Page et al., 2022).

The Rangeland Analysis Platform (RAP) now offers yearly 30 m maps of shrub and tree cover for western US rangelands. Its model was trained on 52,012 field plots and tested on 5,780 plots kept out of training (Allred et al., 2021; Jones et al., 2018). It maps cover by plant type, not by species, so it cannot tell mesquite from juniper.

### Radar plus optical in drylands

Radar measures surface structure and works through clouds. Sentinel-1 is a C-band radar. **VV** and **VH** are its two polarizations (the direction of the sent and received waves); VH responds more to branches and leaves. Across the African Sahel, Sentinel-1 plus Sentinel-2 mapped woody canopies at 10 m with 93% overall accuracy. That beat Sentinel-1 alone (89%) and Sentinel-2 alone (91%) (Zhang et al., 2019). In a Tanzanian savannah, adding radar to optical data raised accuracy in every test, but optical alone still beat radar alone (Borges et al., 2020).

### Summary table

| Study | Place | Sensor(s) | Season / phenology | Features | Classifier | Labels (reference data) | Reported accuracy | How validated |
|---|---|---|---|---|---|---|---|---|
| Ng et al. 2016 | Hargeisa, Somaliland | Landsat 8 | Wet, dry, and both | Bands; pixel vs. object | Random Forest | Field data, 2015 dry season | 74% OA (best) | 10-fold cross-validation |
| Meroni et al. 2017 | West Somaliland | Landsat 8 (30 m and 15 m pan-sharpened) | Wet, dry, and both; *Prosopis* greener in dry season | Bands | Random Forest | 2015 field campaign | 84% OA (best) | Not stated in abstract |
| Ng et al. 2017 | Baringo, Kenya | Sentinel-2; Pléiades | Single date | Object-based spectral | Random Forest | In situ points | S2: OOB 0.79, independent 0.80-0.96 | OOB plus independent test sites from another project |
| Mbaabu et al. 2019 | Baringo, Kenya | Landsat, 1988-2016 | Dry plus wet season | Bands | Random Forest | Not stated in abstract | 98.1-98.5% OA | Not stated in abstract |
| Shiferaw et al. 2019 | Afar, Ethiopia | Landsat 8 plus topography, climate | Dry season (Jan-Feb 2017) | 17 variables; NDVI and elevation ranked top | Random Forest (fractional cover) | 2,722 field plots, at least 500 m apart | 92% accuracy, kappa 0.8 | Random 80/20 split, 10 repeats |
| Wakie et al. 2014 | Afar, Ethiopia | MODIS NDVI/EVI | Time series | Indices plus topo-climate | Maxent | Occurrence points | AUC 0.94-0.95 | Not checked in full text |
| Vaibhav et al. 2012 | Banni, India | Landsat 5 TM | Single 2011 scene | Bands | Maximum likelihood | GPS field points | 94.4% | Not stated |
| Mirik and Ansley 2012 | North Texas | 1 m aerial; Landsat 30 m | Single date | Bands | Image classification (type not in abstract) | Not stated in abstract | 94% (1 m), 87% (30 m) OA | Not stated in abstract |
| Hartfield and van Leeuwen 2018 | Oklahoma, Texas | NAIP 1 m plus Landsat | Multi-season | Reflectance | CART, then Cubist | NAIP woody classification | MAE 12.1%, r = 0.78 | Not stated in abstract |
| Page et al. 2022 | Three Texas ecoregions | UAV plus Sentinel-2 | Not stated in abstract | Spectral plus UAV height | Random Forest | UAV-mapped mesquite | OA > 80% at all sites | Not stated in abstract |
| Allred et al. 2021 (RAP) | Western US rangelands | Landsat time series | Annual | Temporal | Temporal convolutional network | 52,012 field plots | MAE 6.3% | 5,780 held-out plots plus outside datasets |
| Zhang et al. 2019 | African Sahel | Sentinel-1 plus Sentinel-2 | Not stated in abstract | Radar plus optical | Support vector machine | Google Earth very high resolution images | 93% OA (S1 89%, S2 91%) | Independent very high resolution images |
| Borges et al. 2020 | Ngorongoro, Tanzania | Sentinel-1 plus Sentinel-2 | Dry, short-dry, wet | Radar plus optical | Not stated in abstract | Not stated in abstract | 86.3 ± 1.5% OA | Not stated in abstract |

OA = overall accuracy. OOB = out-of-bag: the trees in a Random Forest each skip part of the training data, and those skipped points act as a built-in test. MAE = mean absolute error. "Not stated in abstract" means only the abstract was checked, not the full paper.

## What the accuracies mean

Most of these numbers come from check points drawn from the same pool, in the same area, as the training points. Shiferaw et al. (2019) split field plots at random, 80% for training and 20% for testing. Ng et al. (2016) used 10-fold cross-validation, which also mixes points from across the study area. Out-of-bag accuracy works the same way.

Points close together look alike. So when training and test points are near neighbours, the test is easy, and accuracy can look higher than it will be in a new place. Shiferaw et al. reduced this by keeping plots at least 500 m apart. A few studies used truly separate check data: test sites from another project (Ng et al., 2017), independent high resolution images (Zhang et al., 2019), or held-out field plots (Allred et al., 2021). None of the studies reviewed here held out whole blocks of land for testing.

Overall accuracy also hides the rare class. When most of the map is not *Prosopis*, a map can score high while missing much of the target. Olofsson et al. (2014) set out good practice: sample by mapped class, then report user's and producer's accuracy and an area estimate with a 95% confidence interval. Few of the studies above report area this way.

## What this project follows and where it differs

This project follows the common recipe from the African studies, which Ng et al. (2016) and Meroni et al. (2017) show most clearly. It uses Random Forest on multi-season optical imagery and relies on a season when *Prosopis* looks different. It also takes the main lesson from Zhang et al. (2019): add Sentinel-1 radar to Sentinel-2.

The key change is the phenology. African *P. juliflora* stays green in the dry season. Honey mesquite in Texas does the opposite. Its budbreak "rarely occurs prior to the last spring frost" (Goen and Dahl, 1982), and it drops its leaves in late fall (Steinberg, 2001). Ashe and redberry junipers stay green all year (Sullivan, 1993; Hauser, 2007). So in Texas the useful signal is a late spring green-up and a bare winter, set against evergreen juniper and against grasses that green up on their own schedule.

Other differences:

- **Monthly time series, two sensors.** The project uses monthly Sentinel-2 composites (NDVI, the red-edge index NDRE, and the moisture index NDMI) plus monthly Sentinel-1 VV, VH and VH/VV. Most studies above used one to three dates. NDRE uses the red-edge band, where leaf reflectance rises fast; a red-edge index of this kind was first tied to leaf chlorophyll by Gitelson and Merzlyak (1994). The radar data is the Microsoft Planetary Computer Sentinel-1 RTC product, terrain corrected by the method of Small (2011). It compares S2 only, S1 only, and S1 plus S2.
- **A mapped label product instead of field points.** Labels come from the TPWD Ecological Mapping Systems of Texas, a 10 m map built from 2008 to 2013 (Elliott et al., 2014; Elliott et al., 2009-2014). It is compared with the USGS GAP/LANDFIRE 2011 map (USGS GAP, 2016). Both labels are older than the 2020 imagery and have their own errors, so the model learns the map, not the ground truth.
- **Spatial block validation.** Training and test data come from separate 2 km blocks with a buffer between them. Random and spatial cross-validation are run side by side to show how much random splits overstate accuracy.
- **Area estimates.** Accuracy and mesquite area are reported with the Olofsson et al. (2014) estimators and 95% confidence intervals.
- **Lidar check.** USGS 3DEP lidar height above ground (2015-2018) serves as an optional structure feature and as an independent check that mapped mesquite has shrub height.
- **Importance by month and sensor.** Grouped permutation importance tests whether the months that matter match the phenology above.

## References

Allred, B. W., Bestelmeyer, B. T., Boyd, C. S., Brown, C., Davies, K. W., Duniway, M. C., Ellsworth, L. M., Erickson, T. A., Fuhlendorf, S. D., Griffiths, T. V., Jansen, V., Jones, M. O., Karl, J., Knight, A., Maestas, J. D., Maynard, J. J., McCord, S. E., Naugle, D. E., Starns, H. D., Twidwell, D., and Uden, D. R. (2021). Improving Landsat predictions of rangeland fractional cover with multitask learning and uncertainty. *Methods in Ecology and Evolution*, 12(5), 841-849. https://doi.org/10.1111/2041-210X.13564

Ansley, R. J., Wu, X. B., and Kramp, B. A. (2001). Observation: Long-term increases in mesquite canopy cover in a north Texas savanna. *Journal of Range Management*, 54(2), 171-176. https://doi.org/10.2307/4003179

Asner, G. P., Archer, S., Hughes, R. F., Ansley, R. J., and Wessman, C. A. (2003). Net changes in regional woody vegetation cover and carbon storage in Texas Drylands, 1937-1999. *Global Change Biology*, 9(3), 316-335. https://doi.org/10.1046/j.1365-2486.2003.00594.x

Borges, J., Higginbottom, T. P., Symeonakis, E., and Jones, M. (2020). Sentinel-1 and Sentinel-2 data for savannah land cover mapping: Optimising the combination of sensors and seasons. *Remote Sensing*, 12(23), 3862. https://doi.org/10.3390/rs12233862

Breiman, L. (2001). Random forests. *Machine Learning*, 45(1), 5-32. https://doi.org/10.1023/A:1010933404324

Elliott, L. F., Diamond, D. D., True, C. D., Blodgett, C. F., Pursell, D., German, D., and Treuer-Kuehn, A. (2014). *Ecological Mapping Systems of Texas: Summary Report*. Texas Parks & Wildlife Department, Austin, Texas. https://tpwd.texas.gov/gis/programs/landscape-ecology/supporting-documents/final-summary-report

Elliott, L. F., Treuer-Kuehn, A., Blodgett, C. F., True, C. D., German, D., and Diamond, D. D. (2009-2014). *Ecological Systems of Texas: 391 Mapped Types. Phase 1-6, 10-meter resolution Geodatabase, Interpretive Guides, and Technical Type Descriptions*. Texas Parks & Wildlife Department and Texas Water Development Board, Austin, Texas. Data: https://tpwd.texas.gov/landwater/land/programs/landscape-ecology/ems/emst

Gitelson, A., and Merzlyak, M. N. (1994). Spectral reflectance changes associated with autumn senescence of *Aesculus hippocastanum* L. and *Acer platanoides* L. leaves. Spectral features and relation to chlorophyll estimation. *Journal of Plant Physiology*, 143(3), 286-292. https://doi.org/10.1016/S0176-1617(11)81633-0

Goen, J. P., and Dahl, B. E. (1982). Factors affecting budbreak in honey mesquite in west Texas. *Journal of Range Management*, 35(4), 533-534. https://doi.org/10.2307/3898624

Hartfield, K. A., and van Leeuwen, W. (2018). Woody cover estimates in Oklahoma and Texas using a multi-sensor calibration and validation approach. *Remote Sensing*, 10(4), 632. https://doi.org/10.3390/rs10040632

Hauser, A. S. (2007). *Juniperus pinchotii*. In: Fire Effects Information System. USDA Forest Service, Rocky Mountain Research Station, Fire Sciences Laboratory. https://www.fs.usda.gov/database/feis/plants/tree/junpin/all.html

Jones, M. O., Allred, B. W., Naugle, D. E., Maestas, J. D., Donnelly, P., Metz, L. J., Karl, J., Smith, R., Bestelmeyer, B., Boyd, C., Kerby, J. D., and McIver, J. D. (2018). Innovation in rangeland monitoring: annual, 30 m, plant functional type percent cover maps for U.S. rangelands, 1984-2017. *Ecosphere*, 9(9), e02430. https://doi.org/10.1002/ecs2.2430

Mbaabu, P. R., Ng, W.-T., Schaffner, U., Gichaba, M., Olago, D., Choge, S., Oriaso, S., and Eckert, S. (2019). Spatial evolution of *Prosopis* invasion and its effects on LULC and livelihoods in Baringo, Kenya. *Remote Sensing*, 11(10), 1217. https://doi.org/10.3390/rs11101217

Meroni, M., Ng, W.-T., Rembold, F., Leonardi, U., Atzberger, C., Gadain, H., and Shaiye, M. (2017). Mapping *Prosopis juliflora* in West Somaliland with Landsat 8 satellite imagery and ground information. *Land Degradation & Development*, 28(2), 494-506 (published online 2016). https://doi.org/10.1002/ldr.2611

Microsoft Planetary Computer. Sentinel 1 Radiometrically Terrain Corrected (RTC) [dataset; RTC processing by Catalyst; license CC BY 4.0]. https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc

Mirik, M., and Ansley, R. J. (2012). Utility of satellite and aerial images for quantification of canopy cover and infilling rates of the invasive woody species honey mesquite (*Prosopis glandulosa*) on rangeland. *Remote Sensing*, 4(7), 1947-1962. https://doi.org/10.3390/rs4071947

Ng, W.-T., Meroni, M., Immitzer, M., Böck, S., Leonardi, U., Rembold, F., Gadain, H., and Atzberger, C. (2016). Mapping *Prosopis* spp. with Landsat 8 data in arid environments: Evaluating effectiveness of different methods and temporal imagery selection for Hargeisa, Somaliland. *International Journal of Applied Earth Observation and Geoinformation*, 53, 76-89. https://doi.org/10.1016/j.jag.2016.07.019

Ng, W.-T., Rima, P., Einzmann, K., Immitzer, M., Atzberger, C., and Eckert, S. (2017). Assessing the potential of Sentinel-2 and Pléiades data for the detection of *Prosopis* and *Vachellia* spp. in Kenya. *Remote Sensing*, 9(1), 74. https://doi.org/10.3390/rs9010074

Olofsson, P., Foody, G. M., Herold, M., Stehman, S. V., Woodcock, C. E., and Wulder, M. A. (2014). Good practices for estimating area and assessing accuracy of land change. *Remote Sensing of Environment*, 148, 42-57. https://doi.org/10.1016/j.rse.2014.02.015

Page, M. T., Perotto-Baldivieso, H. L., Ortega-S., J. A., Tanner, E. P., Angerer, J. P., Combs, R. C., Camacho, A. M., Ramirez, M., Cavazos, V., Carroll, H., Baca, K., Daniels, D., and Kimmet, T. (2022). Evaluating mesquite distribution using unpiloted aerial vehicles and satellite imagery. *Rangeland Ecology & Management*, 83, 91-101. https://doi.org/10.1016/j.rama.2022.03.007

Shiferaw, H., Schaffner, U., Bewket, W., Alamirew, T., Zeleke, G., Teketay, D., and Eckert, S. (2019). Modelling the current fractional cover of an invasive alien plant and drivers of its invasion in a dryland ecosystem. *Scientific Reports*, 9, 1576. https://doi.org/10.1038/s41598-018-36587-7

Small, D. (2011). Flattening gamma: Radiometric terrain correction for SAR imagery. *IEEE Transactions on Geoscience and Remote Sensing*, 49(8), 3081-3093. https://doi.org/10.1109/TGRS.2011.2120616

Steinberg, P. (2001). *Prosopis glandulosa*. In: Fire Effects Information System. USDA Forest Service, Rocky Mountain Research Station, Fire Sciences Laboratory. https://www.fs.usda.gov/database/feis/plants/tree/progla/all.html

Sullivan, J. (1993). *Juniperus ashei*. In: Fire Effects Information System. USDA Forest Service, Rocky Mountain Research Station, Fire Sciences Laboratory. https://www.fs.usda.gov/database/feis/plants/tree/junash/all.html

U.S. Geological Survey Gap Analysis Project (2016). GAP/LANDFIRE National Terrestrial Ecosystems 2011. U.S. Geological Survey data release. https://doi.org/10.5066/F7ZS2TM0

Vaibhav, V., Inamdar, A. B., and Bajaj, D. N. (2012). Above ground biomass and carbon stock estimation from *Prosopis juliflora* in Banni grassland using satellite and ancillary data. Asian Conference on Remote Sensing (ACRS) 2012, conference paper. https://acrs-aars.org/proceeding/ACRS2012/Proceeding%20ACRS%202012/Technical%20Sessions/E3%20Other%20(1)/E3-1.pdf

Wakie, T. T., Evangelista, P. H., Jarnevich, C. S., and Laituri, M. (2014). Mapping current and potential distribution of non-native *Prosopis juliflora* in the Afar region of Ethiopia. *PLoS ONE*, 9(11), e112854. https://doi.org/10.1371/journal.pone.0112854

Zhang, W., Brandt, M., Wang, Q., Prishchepov, A. V., Tucker, C. J., Li, Y., Lyu, H., and Fensholt, R. (2019). From woody cover to woody canopies: How Sentinel-1 and Sentinel-2 data advance the mapping of woody plants in savannas. *Remote Sensing of Environment*, 234, 111465. https://doi.org/10.1016/j.rse.2019.111465
