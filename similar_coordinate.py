from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsFields
)

class FindSimilarCoordinatesAlgorithm(QgsProcessingAlgorithm):
    
    INPUT_LAYER = 'INPUT_LAYER'
    DISTANCE = 'DISTANCE'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                'Input Layer',
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.DISTANCE,
                'Buffer Distance (degrees)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.00005  # Default value in degrees (~5.5 meters at the equator)
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                'Output Layer'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        buffer_distance = self.parameterAsDouble(parameters, self.DISTANCE, context)

        # Prepare fields for the output layer
        input_fields = input_layer.fields()
        output_fields = QgsFields(input_fields)
        output_fields.append(QgsField('location_id', QVariant.Int))
        output_fields.append(QgsField('count_id', QVariant.Int))  # New column for count_id

        # Create an empty feature sink
        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT_LAYER, context,
                                               output_fields, QgsWkbTypes.Point, input_layer.sourceCrs())

        # Step 1: Create buffers for each feature
        feature_buffers = []
        num_features = input_layer.featureCount()
        feedback.setProgress(0)

        for index, feature in enumerate(input_layer.getFeatures()):
            buffer_geom = feature.geometry().buffer(buffer_distance, 5)
            feature_buffers.append(buffer_geom)
            feedback.setProgress(int((index / num_features) * 20))  # 0-20% for buffering

        # Step 2: Dissolve buffers into a single geometry
        dissolved_geometry = QgsGeometry.unaryUnion(feature_buffers)
        feedback.setProgress(30)

        # Step 3: Convert dissolved geometry to singlepart geometries
        singlepart_geometries = []
        if dissolved_geometry.isMultipart():
            # If it's a multipart geometry, split it into singleparts
            singlepart_geometries = dissolved_geometry.asGeometryCollection()
        else:
            # If it's already singlepart, just add it to the list
            singlepart_geometries = [dissolved_geometry]
        feedback.setProgress(50)

        # Step 4: Create a new layer for singleparts with unique IDs
        singlepart_layer = QgsVectorLayer("Polygon?crs=" + input_layer.crs().authid(), "singleparts", "memory")
        provider = singlepart_layer.dataProvider()
        provider.addAttributes([QgsField('location_id', QVariant.Int)])
        singlepart_layer.updateFields()

        location_id = 1
        for geom in singlepart_geometries:
            feature = QgsFeature()
            feature.setGeometry(geom)
            feature.setAttributes([location_id])
            provider.addFeature(feature)
            location_id += 1

        singlepart_layer.updateExtents()
        feedback.setProgress(70)

        # Step 5: Create a spatial index for the singlepart layer
        spatial_index = QgsSpatialIndex()
        for feature in singlepart_layer.getFeatures():
            spatial_index.addFeature(feature)

        # Step 6: Count how many features have each location_id
        location_id_count = {}
        for input_feature in input_layer.getFeatures():
            geom = input_feature.geometry()
            intersecting_ids = spatial_index.intersects(geom.boundingBox())
            location_ids = set()
            for id in intersecting_ids:
                singlepart_feature = singlepart_layer.getFeature(id)
                if singlepart_feature.geometry().intersects(geom):
                    location_ids.add(singlepart_feature['location_id'])

            if location_ids:
                assigned_location_id = min(location_ids)
                if assigned_location_id in location_id_count:
                    location_id_count[assigned_location_id] += 1
                else:
                    location_id_count[assigned_location_id] = 1
            else:
                assigned_location_id = None

        # Step 7: Add features to the output layer with assigned location_id and count_id
        for input_feature in input_layer.getFeatures():
            geom = input_feature.geometry()
            intersecting_ids = spatial_index.intersects(geom.boundingBox())
            location_ids = set()
            for id in intersecting_ids:
                singlepart_feature = singlepart_layer.getFeature(id)
                if singlepart_feature.geometry().intersects(geom):
                    location_ids.add(singlepart_feature['location_id'])

            if location_ids:
                assigned_location_id = min(location_ids)
                count_id = location_id_count.get(assigned_location_id, 0)
            else:
                assigned_location_id = None
                count_id = 0

            new_feature = QgsFeature(output_fields)
            new_feature.setGeometry(input_feature.geometry())
            new_feature.setAttributes(input_feature.attributes() + [assigned_location_id, count_id])
            sink.addFeature(new_feature)

        feedback.setProgress(100)
        return {self.OUTPUT_LAYER: dest_id}

    def name(self):
        return 'findsimilarcoordinates'

    def displayName(self):
        return 'Similar Coordinates Based On Distance'

    def createInstance(self):
        return FindSimilarCoordinatesAlgorithm()
