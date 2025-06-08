import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):

    issuerList = ['C=BE,O=GlobalSign nv-sa,CN=GlobalSign RSA OV SSL CA 2018']
    subjectList = [
        'C=BE,ST=Brabant Wallon,L=La Hulpe,O=SWIFT,CN=sandbox.swift.com',
        'C=BE,ST=Brabant Wallon,L=La Hulpe,O=SWIFT,CN=sandbox-test.swift.com',
        'C=BE,ST=Brabant Wallon,L=La Hulpe,O=SWIFT,CN=sandbox-qa.swift.com',
        'C=BE,ST=Brabant Wallon,L=La Hulpe,O=SWIFT,CN=sandbox-dev.swift.com'
    ]
    #serialNumberList = [
    # sandbox.swift.com
    #   '34123369145486558420654644119',
    # sandbox-test.swift.com
    #  '38073806676561326546943885306'
    #]
    sourceIpList = [
        '35.189.89.201', '35.234.131.166', '35.241.130.95', '35.240.37.178',
        '23.194.131.216', '23.194.131.152'
    ]

    authResponse = {'isAuthorized': False}

    try:
        logger.info(json.dumps(event))
        # Retrieve request parameters from the Lambda function input:
        if 'requestContext' in event:
            clientCert = event['requestContext']['authentication'][
                'clientCert']
            http = event['requestContext']['http']

            #if clientCert['issuerDN'] in issuerList and clientCert[
            #   'subjectDN'] in subjectList and clientCert[
            #  'serialNumber'] in serialNumberList and http[
            # 'sourceIp'] in sourceIpList:

            if clientCert['issuerDN'] in issuerList and clientCert[
                'subjectDN'] in subjectList and http[
                'sourceIp'] in sourceIpList:
                authResponse = {'isAuthorized': True}

        return authResponse

    except Exception as e:
        logger.error('Caught Exception:')
        logger.error(e)
        logger.error(json.dumps(event))
        authResponse = {'isAuthorized': False}
        return authResponse
