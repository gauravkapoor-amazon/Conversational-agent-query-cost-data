import boto3
import json

def create_agentcore_gateway_role():
    iam = boto3.client('iam')
    
    # Trust policy for the gateway service role
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    # Core permissions policy
    permissions_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AgentCoreGatewayCore",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeGateway",
                    "bedrock-agentcore:AuthorizeAction",
                    "bedrock-agentcore:PartiallyAuthorizeActions",
                    "bedrock-agentcore:GetPolicyEngine"
                ],
                "Resource": "*"
            },
            {
                "Sid": "CloudWatchLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams"
                ],
                "Resource": "arn:aws:logs:*:*:log-group:/aws/bedrock/agentcore/gateway/*"
            },
            {
                "Sid": "XRayTracing",
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords"
                ],
                "Resource": "*"
            },
            {
                "Sid": "LambdaInvoke",
                "Effect": "Allow",
                "Action": [
                    "lambda:InvokeFunction"
                ],
                "Resource": [
                    "arn:aws:lambda:*:*:function:*"
                ]
            },
            {
                "Sid": "SecretsManagerAccess",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret"
                ],
                "Resource": [
                    "arn:aws:secretsmanager:*:*:secret:agentcore/gateway/*"
                ]
            }
        ]
    }
    
    role_name = "AgentCoreGatewayExecutionRole"
    
    try:
        # Create the role
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for AgentCore Gateway",
            MaxSessionDuration=3600
        )
        
        # Create and attach the permissions policy
        policy_response = iam.create_policy(
            PolicyName=f"{role_name}Policy",
            PolicyDocument=json.dumps(permissions_policy),
            Description="Permissions policy for AgentCore Gateway execution role"
        )
        
        # Attach the policy to the role
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn=policy_response['Policy']['Arn']
        )
        
        print(f"Successfully created role: {role_response['Role']['Arn']}")
        return role_response['Role']['Arn']
        
    except Exception as e:
        print(f"Error creating role: {str(e)}")
        return None

# Usage
if __name__ == "__main__":
    role_arn = create_agentcore_gateway_role()
    if role_arn:
        print(f"Gateway role created successfully: {role_arn}")
