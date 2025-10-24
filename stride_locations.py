# Save this code as 'get_stride_data_duration_qgs.py'

from qgis.PyQt.QtCore import QCoreApplication, QDateTime, Qt, QVariant, QUrl, QEventLoop
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterString,
                       QgsProcessingParameterExtent,
                       QgsProcessingParameterDateTime,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingException,
                       QgsVectorLayer,
                       QgsProject,
                       QgsFields,
                       QgsField,
                       QgsFeature,
                       QgsFeatureSink,
                       QgsGeometry,
                       QgsPointXY,
                       QgsWkbTypes,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform,
                       QgsNetworkAccessManager) # <--- IMPORT QgsNetworkAccessManager

# urllib.request is no longer needed
import urllib.parse
import json

class GetStrideDataDurationAlgo(QgsProcessingAlgorithm):
    """
    Fetches data from the Open Bus Stride API using a start time and duration,
    and saves it as a typed layer in the Israel Grid (EPSG:2039) CRS.
    """
    INPUT_PATH = 'INPUT_PATH'
    INPUT_PARAMS = 'INPUT_PARAMS'
    INPUT_EXTENT = 'INPUT_EXTENT'
    INPUT_START_TIME = 'INPUT_START_TIME'
    INPUT_DURATION = 'INPUT_DURATION'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return GetStrideDataDurationAlgo()

    def name(self):
        return 'getstridedataduration'

    def displayName(self):
        return self.tr('Get Open Bus Stride Data (by Duration)')

    def group(self):
        return self.tr('Web')

    def groupId(self):
        return 'web'

    def shortHelpString(self):
        return self.tr("""
        Fetches vehicle location data using a start time and a duration in minutes.
        The output layer will be in the Israel Grid (EPSG:2039) CRS.
        The script uses a field schema optimized for vehicle location data.
        This version uses QgsNetworkAccessManager for network requests.
        """)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_PATH, self.tr('API Path'),
                defaultValue='/siri_vehicle_locations/list'
            ))
        self.addParameter(
            QgsProcessingParameterExtent(
                self.INPUT_EXTENT, self.tr('Filter by Extent'),
                optional=True
            ))
        self.addParameter(
            QgsProcessingParameterDateTime(
                self.INPUT_START_TIME, self.tr('Start Time (UTC)'),
                optional=True
            ))
        self.addParameter(
            QgsProcessingParameterNumber(
                self.INPUT_DURATION,
                self.tr('Duration (minutes)'),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=5,
                minValue=1,
                optional=True
            ))
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_PARAMS,
                self.tr('Additional Request Parameters (as Python dictionary)'),
                optional=True, defaultValue="{'limit': 1000}"
            ))
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr('Output layer')
            ))

    def processAlgorithm(self, parameters, context, feedback):
        base_url = 'https://open-bus-stride-api.hasadna.org.il'
        api_path = self.parameterAsString(parameters, self.INPUT_PATH, context)
        params_str = self.parameterAsString(parameters, self.INPUT_PARAMS, context)
        extent = self.parameterAsExtent(parameters, self.INPUT_EXTENT, context)
        extent_crs = self.parameterAsExtentCrs(parameters, self.INPUT_EXTENT, context)
        start_time = self.parameterAsDateTime(parameters, self.INPUT_START_TIME, context)
        duration_minutes = self.parameterAsInt(parameters, self.INPUT_DURATION, context)

        params = {}
        if params_str:
            try:
                params = eval(params_str)
                if not isinstance(params, dict): raise TypeError
            except (SyntaxError, TypeError):
                raise QgsProcessingException(self.tr("Invalid format for parameters."))

        if not extent.isNull():
            target_crs = QgsCoordinateReferenceSystem('EPSG:4326')
            transform = QgsCoordinateTransform(extent_crs, target_crs, context.transformContext())
            extent_wgs84 = transform.transform(extent)
            params['lon__greater_or_equal'] = extent_wgs84.xMinimum()
            params['lon__lower_or_equal'] = extent_wgs84.xMaximum()
            params['lat__greater_or_equal'] = extent_wgs84.yMinimum()
            params['lat__lower_or_equal'] = extent_wgs84.yMaximum()

        iso_format = "yyyy-MM-ddTHH:mm:ss.zzz'Z'"
        if start_time.isValid():
            params['recorded_at_time_from'] = start_time.toString(iso_format)
            feedback.pushInfo(self.tr(f'Filtering from start time: {params["recorded_at_time_from"]}'))
            
            if duration_minutes > 0:
                end_time = start_time.addSecs(duration_minutes * 60)
                params['recorded_at_time_to'] = end_time.toString(iso_format)
                feedback.pushInfo(self.tr(f'Calculated end time: {params["recorded_at_time_to"]}'))
            
        query_string = urllib.parse.urlencode(params, safe=':')
        url = QUrl(f"{base_url}{api_path}")
        url.setQuery(query_string)
        
        feedback.pushInfo(self.tr(f'Requesting data from: {url.toString()}'))

        # --- MODIFIED: Use QgsNetworkAccessManager instead of urllib ---
        manager = QgsNetworkAccessManager.instance()
        request = QNetworkRequest(url)
        reply = manager.get(request)

        # Use an event loop to wait for the reply to finish (makes the call synchronous)
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        loop.exec_()
        
        data = []
        try:
            if reply.error():
                raise QgsProcessingException(self.tr(f"Network request failed: {reply.errorString()}"))

            status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status_code != 200:
                raise QgsProcessingException(
                    self.tr(f"API request failed with HTTP status code {status_code}"))
            
            response_body = reply.readAll()
            data = json.loads(bytes(response_body).decode('utf-8'))

        except json.JSONDecodeError as e:
            raise QgsProcessingException(self.tr(f"Failed to parse JSON response: {e}"))
        finally:
            # Ensure the reply object is cleaned up to prevent memory leaks
            reply.deleteLater()
        # --- END MODIFICATION ---
        
        if not isinstance(data, list) or not data:
            feedback.pushInfo(self.tr("Response did not contain a list of items or was empty."))
            return {self.OUTPUT: None}
        
        final_fields = QgsFields()
        field_definitions = [
            ('id', QVariant.LongLong), ('snapshot_id', QVariant.LongLong), ('ride_stop_id', QVariant.LongLong),
            ('recorded_at', QVariant.DateTime), ('lon', QVariant.Double), ('lat', QVariant.Double),
            ('bearing', QVariant.Int), ('velocity', QVariant.Int), ('dist_from_start', QVariant.Int),
            ('dist_from_stop', QVariant.Double), ('snapshot_str', QVariant.String), ('route_id', QVariant.Int),
            ('line_ref', QVariant.Int), ('operator_ref', QVariant.Int), ('ride_id', QVariant.LongLong),
            ('journey_ref', QVariant.String), ('scheduled_start', QVariant.DateTime), ('vehicle_ref', QVariant.String),
        ]
        for name, type in field_definitions:
            final_fields.append(QgsField(name, type))

        key_map = {
            'siri_snapshot_id': 'snapshot_id', 'siri_ride_stop_id': 'ride_stop_id', 'recorded_at_time': 'recorded_at',
            'distance_from_journey_start': 'dist_from_start', 'distance_from_siri_ride_stop_meters': 'dist_from_stop',
            'siri_snapshot__snapshot_id': 'snapshot_str', 'siri_route__id': 'route_id', 'siri_route__line_ref': 'line_ref',
            'siri_route__operator_ref': 'operator_ref', 'siri_ride__id': 'ride_id', 'siri_ride__journey_ref': 'journey_ref',
            'siri_ride__scheduled_start_time': 'scheduled_start', 'siri_ride__vehicle_ref': 'vehicle_ref',
        }
        
        source_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        dest_crs = QgsCoordinateReferenceSystem('EPSG:2039')
        
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, final_fields,
            QgsWkbTypes.Point, dest_crs 
        )
        if sink is None:
            raise QgsProcessingException(self.tr('Invalid output specified.'))
        
        transform = QgsCoordinateTransform(source_crs, dest_crs, context.transformContext())

        total = len(data)
        feedback.pushInfo(f'Processing {total} features...')
        
        for i, item in enumerate(data):
            if feedback.isCanceled(): break
            feature = QgsFeature(final_fields)
            
            if item.get('lon') is not None and item.get('lat') is not None:
                try:
                    point_wgs84 = QgsPointXY(float(item['lon']), float(item['lat']))
                    geom = QgsGeometry.fromPointXY(transform.transform(point_wgs84))
                    feature.setGeometry(geom)
                except (ValueError, TypeError):
                    continue

            attributes = []
            for field in final_fields:
                original_key = next((k for k, v in key_map.items() if v == field.name()), field.name())
                val = item.get(original_key)
                
                if val is None:
                    attributes.append(QVariant())
                elif field.type() == QVariant.DateTime:
                    dt = QDateTime.fromString(val, Qt.ISODate)
                    attributes.append(dt)
                else:
                    attributes.append(val)
            
            feature.setAttributes(attributes)
            sink.addFeature(feature, QgsFeatureSink.FastInsert)
            feedback.setProgress(int((i + 1) / total * 100))

        return {self.OUTPUT: dest_id}