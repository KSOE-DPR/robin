#include "ros/ros.h"
#include "robin_bridge/robin_inst.cpp"
int main(int argc, char **argv)
{
  ros::init(argc, argv, "robin");
  ros::NodeHandle nh;
  RobinSubscriber<double, std_msgs::Float64> double_to_codesys(nh, "double_to_codesys");
  RobinPublisher<double, std_msgs::Float64> double_to_ros(nh, "double_to_ros");
  ros::spin();
  return 0;
}