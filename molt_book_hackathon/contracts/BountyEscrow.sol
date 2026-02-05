// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function transfer(address to, uint256 value) external returns (bool);
}

contract BountyEscrow {
    IERC20 public immutable usdc;
    uint256 public bountyCount;

    struct Bounty {
        address creator;
        address arbiter;
        uint256 amount;
        uint64 deadline;
        bool awarded;
        bool canceled;
        address winner;
        uint32 submissions;
    }

    mapping(uint256 => Bounty) public bounties;
    mapping(uint256 => mapping(address => bool)) public hasSubmitted;

    event BountyCreated(
        uint256 indexed bountyId,
        address indexed creator,
        address indexed arbiter,
        uint256 amount,
        uint64 deadline,
        string metadataURI
    );
    event Submission(uint256 indexed bountyId, address indexed solver, string solutionURI);
    event Awarded(uint256 indexed bountyId, address indexed solver, uint256 amount);
    event Refunded(uint256 indexed bountyId, address indexed to, uint256 amount);
    event Canceled(uint256 indexed bountyId);

    constructor(address usdcAddress) {
        require(usdcAddress != address(0), "usdc");
        usdc = IERC20(usdcAddress);
    }

    function createBounty(
        uint256 amount,
        uint64 deadline,
        address arbiter,
        string calldata metadataURI
    ) external returns (uint256) {
        require(amount > 0, "amount");
        require(deadline > block.timestamp, "deadline");

        address finalArbiter = arbiter == address(0) ? msg.sender : arbiter;
        require(usdc.transferFrom(msg.sender, address(this), amount), "transferFrom");

        bountyCount += 1;
        uint256 bountyId = bountyCount;

        bounties[bountyId] = Bounty({
            creator: msg.sender,
            arbiter: finalArbiter,
            amount: amount,
            deadline: deadline,
            awarded: false,
            canceled: false,
            winner: address(0),
            submissions: 0
        });

        emit BountyCreated(bountyId, msg.sender, finalArbiter, amount, deadline, metadataURI);
        return bountyId;
    }

    function submitSolution(uint256 bountyId, string calldata solutionURI) external {
        Bounty storage bounty = bounties[bountyId];
        require(bounty.creator != address(0), "missing");
        require(!bounty.awarded, "awarded");
        require(!bounty.canceled, "canceled");
        require(block.timestamp <= bounty.deadline, "expired");

        bounty.submissions += 1;
        if (!hasSubmitted[bountyId][msg.sender]) {
            hasSubmitted[bountyId][msg.sender] = true;
        }

        emit Submission(bountyId, msg.sender, solutionURI);
    }

    function awardBounty(uint256 bountyId, address solver) external {
        Bounty storage bounty = bounties[bountyId];
        require(bounty.creator != address(0), "missing");
        require(!bounty.awarded, "awarded");
        require(!bounty.canceled, "canceled");
        require(msg.sender == bounty.arbiter, "arbiter");
        require(solver != address(0), "solver");
        require(hasSubmitted[bountyId][solver], "no submission");

        bounty.awarded = true;
        bounty.winner = solver;

        require(usdc.transfer(solver, bounty.amount), "transfer");
        emit Awarded(bountyId, solver, bounty.amount);
    }

    function cancelBounty(uint256 bountyId) external {
        Bounty storage bounty = bounties[bountyId];
        require(bounty.creator != address(0), "missing");
        require(!bounty.awarded, "awarded");
        require(!bounty.canceled, "canceled");
        require(msg.sender == bounty.creator, "creator");
        require(bounty.submissions == 0, "submitted");
        require(block.timestamp <= bounty.deadline, "expired");

        bounty.canceled = true;
        require(usdc.transfer(bounty.creator, bounty.amount), "transfer");
        emit Canceled(bountyId);
    }

    function refundBounty(uint256 bountyId) external {
        Bounty storage bounty = bounties[bountyId];
        require(bounty.creator != address(0), "missing");
        require(!bounty.awarded, "awarded");
        require(!bounty.canceled, "canceled");
        require(block.timestamp > bounty.deadline, "not expired");
        require(msg.sender == bounty.creator || msg.sender == bounty.arbiter, "auth");

        bounty.canceled = true;
        require(usdc.transfer(bounty.creator, bounty.amount), "transfer");
        emit Refunded(bountyId, bounty.creator, bounty.amount);
    }

    function getBounty(uint256 bountyId) external view returns (Bounty memory) {
        return bounties[bountyId];
    }
}
