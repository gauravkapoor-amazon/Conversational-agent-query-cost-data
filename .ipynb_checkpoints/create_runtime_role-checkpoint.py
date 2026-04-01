import boto3
import json

def create_agentcore_runtime_role(account_id: str, region: str = "us-east-1"):
    iam = boto3.client('iam')
    
    # Trust policy for AgentCore Runtime
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": account_id
                    },
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:*:{account_id}:*"
                    }
                }
            }
        ]
    }
    
    # Comprehensive permissions policy
    permissions_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockModelAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*"
                ]
            },
            {
                "Sid": "BedrockKnowledgeBaseAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                "Resource": [
                    "arn:aws:bedrock:*:*:knowledge-base/*"
                ]
            },
            {
                "Sid": "AgentCoreGatewayAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeGateway",
                    "bedrock-agentcore:ListTools",
                    "bedrock-agentcore:GetTarget"
                ],
                "Resource": [
                    "arn:aws:bedrock-agentcore:*:*:gateway/*"
                ]
            },
            {
                "Sid": "AgentCoreMemoryAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetMemorySession",
                    "bedrock-agentcore:PutMemorySession",
                    "bedrock-agentcore:DeleteMemorySession",
                    "bedrock-agentcore:ListMemorySessions"
                ],
                "Resource": [
                    "arn:aws:bedrock-agentcore:*:*:memory/*"
                ]
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
                "Resource": [
                    "arn:aws:logs:*:*:log-group:/aws/bedrock/agentcore/runtime/*"
                ]
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
                "Sid": "SecretsManagerAccess",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret"
                ],
                "Resource": [
                    "arn:aws:secretsmanager:*:*:secret:agentcore/runtime/*"
                ]
            }
        ]
    }
    
    role_name = "AgentCoreRuntimeExecutionRole"
    
    try:
        # Create the role
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for AgentCore Runtime agents",
            MaxSessionDuration=3600
        )
        
        # Create and attach the permissions policy
        policy_response = iam.create_policy(
            PolicyName=f"{role_name}Policy",
            PolicyDocument=json.dumps(permissions_policy),
            Description="Permissions policy for AgentCore Runtime execution role"
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
    account_id = "381491969808"  # Replace with your AWS account ID
    role_arn = create_agentcore_runtime_role(account_id)
    if role_arn:
        print(f"Runtime role created successfully: {role_arn}")
